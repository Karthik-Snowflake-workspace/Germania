from pathlib import Path
import sys

sys.dont_write_bytecode = True

# ============================================================
# LOAD CONFIGURATION
# ============================================================

ROOT = Path.cwd().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.config import config

# ============================================================
# CONFIG
# ============================================================

BRANCH_DATA = config.branch_data
ROLES = config.roles
ADMIN_ROLE = config.admin_role
DCM_PROJECT_NAME = config.dcm_project_name

# Use all unique schemas across branches
ALL_SCHEMAS = config.all_schemas

# Use first database from first branch as reference for discovery
_first_branch = next(iter(BRANCH_DATA.values()), {})
_first_db_list = _first_branch.get("sf_databases", [])
reference_db = _first_db_list[0] if _first_db_list else None

if not reference_db:
    raise RuntimeError("No databases found in branch_data.")

# ============================================================
# DYNAMIC GRANT DISCOVERY
# ============================================================

from snowflake.snowpark.context import get_active_session

session = get_active_session()

# ---------- Purely rule-based plural/singular conversion ----------

def _pluralize(singular):
    """Convert singular object type to plural form using English rules."""
    words = singular.split()
    last = words[-1]
    if last.endswith("Y") and last[-2:] not in ("AY", "EY", "OY", "UY"):
        words[-1] = last[:-1] + "IES"
    elif last.endswith(("S", "X", "Z", "SH", "CH")):
        words[-1] = last + "ES"
    else:
        words[-1] = last + "S"
    return " ".join(words)


def _singularize(plural):
    """Convert plural object type to singular form using English rules."""
    words = plural.split()
    last = words[-1]
    if last.endswith("IES") and len(last) > 4 and last[-4] not in "AEIOU":
        words[-1] = last[:-3] + "Y"
    elif last.endswith("ES") and (
        last[:-2].endswith(("S", "X", "Z", "SH", "CH"))
    ):
        words[-1] = last[:-2]
    elif last.endswith("S") and not last.endswith("SS"):
        words[-1] = last[:-1]
    return " ".join(words)


# ============================================================
# DISCOVER OBJECT TYPES FROM ALL CONFIGURED SCHEMAS
# ============================================================

print("\nDiscovering object types from Snowflake...")

def _discover_info_schema_object_types(database, schema):
    additional_types = set()
    try:
        views = session.sql(
            f"SHOW VIEWS IN SCHEMA {database}.INFORMATION_SCHEMA"
        ).collect()

        fqn = f"{database}.{schema}"
        for row in views:
            data = row.as_dict(recursive=True)
            view_name = data.get("name", "").upper()
            if not view_name:
                continue
            try:
                results = session.sql(
                    f"SHOW {view_name} IN SCHEMA {fqn}"
                ).collect()
                if results:
                    singular = _singularize(view_name)
                    additional_types.add(singular)
            except Exception:
                pass
    except Exception as e:
        print(f"  Info: Could not query INFORMATION_SCHEMA views: {e}")

    return additional_types


def discover_object_types_in_schema(database, schema):
    object_types = set()
    fqn = f"{database}.{schema}"

    results = session.sql(
        f"SHOW OBJECTS IN SCHEMA {fqn}"
    ).collect()

    print(f"\nSchema: {fqn}")

    if not results:
        print("  No objects found via SHOW OBJECTS.")
    else:
        for row in results:
            data = row.as_dict(recursive=True)
            object_name = data.get("name", "<UNKNOWN>")
            object_type = data.get("kind", "<UNKNOWN>")
            print(f"  {object_name:<35} {object_type}")
            if object_type:
                object_types.add(object_type.upper())

    additional = _discover_info_schema_object_types(database, schema)
    if additional:
        print(f"  Additional types discovered: {', '.join(sorted(additional))}")
    object_types.update(additional)

    return {
        obj_type: _pluralize(obj_type)
        for obj_type in sorted(object_types)
    }

# ------------------------------------------------------------
# Discover object types across all configured schemas
# ------------------------------------------------------------

OBJECT_TYPE_PLURAL_MAP = {}

for schema in ALL_SCHEMAS:
    try:
        discovered = discover_object_types_in_schema(reference_db, schema)
        OBJECT_TYPE_PLURAL_MAP.update(discovered)
        print(f"  Object types in {schema}: "
              f"{', '.join(sorted(discovered.keys())) if discovered else 'None'}")
    except Exception as e:
        if "does not exist or not authorized" in str(e) or "1304" in str(e):
            print(f"  Schema {schema} does not exist in this environment. Skipping.")
            continue
        print(f"  Warning: Could not discover objects in {reference_db}.{schema}: {e}")

# ------------------------------------------------------------
# Fallback: if nothing discovered, query account-level object types
# ------------------------------------------------------------

if not OBJECT_TYPE_PLURAL_MAP:
    print("\nWarning: No object types discovered via schema probing.")
    print("  Falling back to SHOW OBJECTS IN DATABASE...")
    try:
        results = session.sql(
            f"SHOW OBJECTS IN DATABASE {reference_db}"
        ).collect()
        for row in results:
            data = row.as_dict(recursive=True)
            kind = data.get("kind", "")
            if kind:
                k = kind.upper()
                OBJECT_TYPE_PLURAL_MAP[k] = _pluralize(k)
    except Exception as e:
        print(f"  Fallback also failed: {e}")
        print("  Using minimal dynamic discovery from INFORMATION_SCHEMA...")
        try:
            results = session.sql(
                f"SHOW VIEWS IN SCHEMA {reference_db}.INFORMATION_SCHEMA"
            ).collect()
            for row in results:
                data = row.as_dict(recursive=True)
                view_name = data.get("name", "").upper()
                if view_name:
                    singular = _singularize(view_name)
                    OBJECT_TYPE_PLURAL_MAP[singular] = view_name
        except Exception:
            pass

print("\n============================================================")
print("Discovered Object Types Across All Schemas")
print("============================================================")

for obj_type in sorted(OBJECT_TYPE_PLURAL_MAP.keys()):
    print(f"  - {obj_type}")

print("============================================================")


def discover_role_grants(role_name):
    schema_create_grants = set()
    object_privileges = {}

    try:
        results = session.sql(
            f"SHOW GRANTS TO ROLE {role_name}"
        ).collect()

        for row in results:
            data = row.as_dict(recursive=True)

            privilege = data["privilege"]
            granted_on = data["granted_on"]

            if granted_on == "SCHEMA" and privilege.startswith("CREATE"):
                schema_create_grants.add(privilege)

            if granted_on in OBJECT_TYPE_PLURAL_MAP:
                object_privileges.setdefault(granted_on, set()).add(privilege)

    except Exception as e:
        print(f"Warning: Could not run SHOW GRANTS TO ROLE {role_name}: {e}")

    return (
        sorted(schema_create_grants),
        {k: sorted(v) for k, v in object_privileges.items()},
    )


def discover_future_grants_for_role(database, schema, role_name):
    future_grants = {}

    try:
        fqn = f"{database}.{schema}"

        results = session.sql(
            f"SHOW FUTURE GRANTS IN SCHEMA {fqn}"
        ).collect()

        for row in results:
            data = row.as_dict(recursive=True)

            grantee = (
                data.get("grantee_name")
                or data.get("grantee")
                or ""
            )

            if grantee.upper() != role_name.upper():
                continue

            grant_on = data["grant_on"]
            privilege = data["privilege"]

            future_grants.setdefault(grant_on, set()).add(privilege)

    except Exception as e:
        if "does not exist or not authorized" in str(e) or "1304" in str(e):
            return {}  # Silently skip missing schemas
        print(f"Warning: Could not run SHOW FUTURE GRANTS IN SCHEMA {database}.{schema}: {e}")

    return {
        k: sorted(v)
        for k, v in future_grants.items()
    }


# ============================================================
# DISCOVER GRANTS PER ROLE
# ============================================================

ROLE_GRANTS = {}

for role_name in ROLES.keys():

    print(f"\n{'=' * 60}")
    print(f"Role : {role_name}")
    print(f"{'=' * 60}")

    schema_create, obj_privs = discover_role_grants(role_name)

    future = {}

    for schema in ALL_SCHEMAS:
        schema_future = discover_future_grants_for_role(
            reference_db,
            schema,
            role_name
        )

        for obj_type, privileges in schema_future.items():
            future.setdefault(obj_type, set()).update(privileges)

    future = {
        k: sorted(v)
        for k, v in future.items()
    }

    # Fallback: derive from discovered object types
    if not schema_create and not future:
        print(f"Warning: No grants discovered for {role_name}. Deriving from discovered types.")

        schema_create = sorted(
            f"CREATE {obj_type}" for obj_type in OBJECT_TYPE_PLURAL_MAP.keys()
        )

        future = {}
        for obj_type, plural in OBJECT_TYPE_PLURAL_MAP.items():
            try:
                privs_result = session.sql(
                    f"SHOW GRANTS ON {obj_type} IN SCHEMA {reference_db}.{ALL_SCHEMAS[0]}"
                ).collect()
                if privs_result:
                    discovered_privs = set()
                    for r in privs_result:
                        d = r.as_dict(recursive=True)
                        p = d.get("privilege", "")
                        if p and p not in ("OWNERSHIP",):
                            discovered_privs.add(p)
                    if discovered_privs:
                        future[obj_type] = sorted(discovered_privs)
                        continue
            except Exception:
                pass
            if "TABLE" in obj_type or "VIEW" in obj_type:
                future[obj_type] = ["SELECT"]
            else:
                future[obj_type] = ["USAGE"]

    ROLE_GRANTS[role_name] = {
        "schema_create_grants": schema_create,
        "object_privileges": obj_privs,
        "future_grants": future,
    }

    print("\nSchema CREATE Privileges")
    print("------------------------")
    print(schema_create)

    print("\nObject Privileges")
    print("-----------------")
    print(obj_privs)

    print("\nFuture Grants")
    print("-------------")
    print(future)

# ============================================================
# BUILD ENV CONFIG
# ============================================================

ENV_CONFIG = {}

for branch_name, branch in BRANCH_DATA.items():
    databases = branch.get("sf_databases", [])
    schemas = branch.get("sf_schemas", [])
    branch_roles = branch.get("sf_roles", list(ROLES.keys()))

    for db_name in databases:
        ENV_CONFIG[branch_name] = {
            "database": db_name,
            "schemas": schemas,
            "roles": {role: role for role in branch_roles},
        }

# ============================================================
# LOCATE PROJECT DIRECTORY
# ============================================================

from config.config import PROJECT_DIR, MACROS_DIR, DEFINITIONS_DIR

MACROS_DIR.mkdir(parents=True, exist_ok=True)
DEFINITIONS_DIR.mkdir(parents=True, exist_ok=True)

DEFINITION_DIR = DEFINITIONS_DIR

print(f"\nProject directory    : {PROJECT_DIR}")
print(f"Macros directory     : {MACROS_DIR}")
print(f"Definition directory : {DEFINITION_DIR}")

# ============================================================
# GENERATE MACRO (per-role differentiated grants)
# ============================================================
def generate_grants_macro():

    lines = []

    lines.append(
        "{% macro create_dcm_project(database, schemas, roles, project_owner_role) %}"
    )
    lines.append("")

    for role_name, grants in ROLE_GRANTS.items():
        schema_create = grants["schema_create_grants"]
        future = grants["future_grants"]

        lines.append(f"-- Grants for logical role: {role_name}")
        lines.append(f"{{% set env_role = roles['{role_name}'] %}}")
        lines.append("")

        lines.append(
            "GRANT USAGE ON DATABASE {{ database }} TO ROLE {{ env_role }};"
        )
        lines.append("")

        lines.append("{% for schema in schemas %}")
        lines.append("{% set full_schema = database ~ '.' ~ schema %}")
        lines.append("")

        lines.append(
            "GRANT USAGE ON SCHEMA {{ full_schema }} TO ROLE {{ env_role }};"
        )
        lines.append("")

        for privilege in schema_create:
            lines.append(
                f"GRANT {privilege} ON SCHEMA {{{{ full_schema }}}} TO ROLE {{{{ env_role }}}};"
            )

        if schema_create:
            lines.append("")

        for obj_type, privileges in future.items():
            plural = OBJECT_TYPE_PLURAL_MAP.get(obj_type, _pluralize(obj_type))
            for priv in privileges:
                lines.append(
                    f"GRANT {priv} ON ALL {plural} IN SCHEMA {{{{ full_schema }}}} TO ROLE {{{{ env_role }}}};"
                )
                lines.append(
                    f"GRANT {priv} ON FUTURE {plural} IN SCHEMA {{{{ full_schema }}}} TO ROLE {{{{ env_role }}}};"
                )

        lines.append("")
        lines.append("{% endfor %}")
        lines.append("")

    lines.append("{% endmacro %}")

    return "\n".join(lines)

# ============================================================
# DEMO FILE
# ============================================================

def generate_demo():

    return """
-- Execute RBAC Macro

{{ create_dcm_project(
    database,
    schemas,
    roles,
    project_owner_role
) }}
"""

# ============================================================
# WRITE FILES
# ============================================================

(MACROS_DIR / "grants_macro.sql").write_text(
    generate_grants_macro(),
    encoding="utf-8",
)

(DEFINITION_DIR / "jinja_demo.sql").write_text(
    generate_demo(),
    encoding="utf-8",
)

print("=" * 60)
print("Files generated successfully.")
print(f"Macro file      : {MACROS_DIR / 'grants_macro.sql'}")
print(f"Definition file : {DEFINITION_DIR / 'jinja_demo.sql'}")
print("=" * 60)
