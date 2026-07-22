from snowflake.snowpark.context import get_active_session
from pathlib import Path
import sys
import re

session = get_active_session()

sys.dont_write_bytecode = True

# ============================================================
# LOAD CONFIGURATION
# ============================================================

ROOT = Path.cwd().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# from config.config import config, PROJECT_DIR, DEFINITIONS_DIR
import importlib
import config.config as cfg
importlib.reload(cfg)

config = cfg.config
LOGS_DIR = cfg.LOGS_DIR
PROJECT_DIR = cfg.PROJECT_DIR
DEFINITIONS_DIR = cfg.DEFINITIONS_DIR
# ============================================================
# CONFIG
# ============================================================

DCM_PROJECT_NAME = config.dcm_project_name
BRANCH_DATA = config.branch_data
ROLES = config.roles
ALL_SCHEMAS = config.all_schemas
ADMIN_ROLE = config.admin_role.upper()

# All configured databases across all branches
ALL_DB_NAMES = config.all_databases

# DEV databases — only these are used for object definitions
_dev_branch = BRANCH_DATA.get("dev", {})
DEV_DATABASES = _dev_branch.get("sf_databases", [])
DEV_SCHEMAS = _dev_branch.get("sf_schemas", ALL_SCHEMAS)

TARGET_DB = "{{ database }}"

ROLES_CONFIG = ROLES

SYSTEM_OWNERS = {"SYSTEM", "SNOWFLAKE", "ACCOUNTADMIN", "ORGADMIN", ADMIN_ROLE}

# ============================================================
# OBJECT TYPE REGISTRY
# ============================================================

OBJECT_REGISTRY = [
    # (object_type, folder_name, show_command_template, uses_get_ddl, get_ddl_type_override)
    ("DYNAMIC TABLE",     "dynamic_tables",      "SHOW DYNAMIC TABLES IN SCHEMA {fqn}",     True,  None),
    ("TABLE",             "tables",              "SHOW TABLES IN SCHEMA {fqn}",              True,  None),
    ("VIEW",              "views",               "SHOW VIEWS IN SCHEMA {fqn}",               True,  None),
    ("MATERIALIZED VIEW", "materialized_views",  "SHOW MATERIALIZED VIEWS IN SCHEMA {fqn}",  True,  None),
    ("EXTERNAL TABLE",    "external_tables",     "SHOW EXTERNAL TABLES IN SCHEMA {fqn}",     True,  None),
    ("STAGE",             "stages",              "SHOW STAGES IN SCHEMA {fqn}",              False, None),
    ("STREAM",            "streams",             "SHOW STREAMS IN SCHEMA {fqn}",             False, None),
    ("TASK",              "tasks",               "SHOW TASKS IN SCHEMA {fqn}",               True,  None),
    ("FILE FORMAT",       "file_formats",        "SHOW FILE FORMATS IN SCHEMA {fqn}",        False, None),
    ("PROCEDURE",         "stored_procedures",   None,                                       True,  None),
    ("FUNCTION",          "functions",           "SHOW USER FUNCTIONS IN SCHEMA {fqn}",      True,  None),
    ("PIPE",              "pipes",               "SHOW PIPES IN SCHEMA {fqn}",               True,  None),
    ("SEQUENCE",          "sequences",           "SHOW SEQUENCES IN SCHEMA {fqn}",           False, None),
    ("MASKING POLICY",    "masking_policies",    "SHOW MASKING POLICIES IN SCHEMA {fqn}",    True,  "MASKING_POLICY"),
    ("ROW ACCESS POLICY", "row_access_policies", "SHOW ROW ACCESS POLICIES IN SCHEMA {fqn}", True, "ROW_ACCESS_POLICY"),
    ("TAG",               "tags",               "SHOW TAGS IN SCHEMA {fqn}",                True,  None),
    ("ALERT",             "alerts",             "SHOW ALERTS IN SCHEMA {fqn}",              True,  None),
]

# Build FOLDER_MAP from registry
FOLDER_MAP = {obj_type: folder for obj_type, folder, *_ in OBJECT_REGISTRY}
FOLDER_MAP["OTHER"] = "others"

# ============================================================
# LOCATE PROJECT DIRECTORY
# ============================================================

TARGET_ROOT = DEFINITIONS_DIR
TARGET_ROOT.mkdir(parents=True, exist_ok=True)

print("=" * 60)
print(f"Project       : {DCM_PROJECT_NAME}")
print(f"All DBs       : {', '.join(ALL_DB_NAMES)}")
print(f"DEV DBs       : {', '.join(DEV_DATABASES)} (object definitions)")
print(f"DEV Schemas   : {', '.join(DEV_SCHEMAS)}")
print(f"Definitions   : {TARGET_ROOT}")
print("=" * 60)

# ============================================================
# HELPERS
# ============================================================

def fq(name, schema):
    return f"{TARGET_DB}.{schema}.{name}"


def replace_env(text):
    """Replace all configured database names with {{ database }} placeholder."""
    if not text:
        return text
    for db_name in ALL_DB_NAMES:
        text = re.sub(rf"\b{db_name}\b", TARGET_DB, text, flags=re.IGNORECASE)
    return text


def get_path(obj_type, object_name, db_name, schema):
    folder = FOLDER_MAP.get(obj_type, "others")
    folder_path = TARGET_ROOT / folder
    folder_path.mkdir(parents=True, exist_ok=True)
    filename = f"{db_name}.{schema}.{object_name}.sql"
    return folder_path / filename


def is_system_procedure(row, database, current_schema):
    owner = (row.get("PROCEDURE_OWNER") or "").upper()
    name = (row.get("PROCEDURE_NAME") or "").upper()
    catalog = (row.get("PROCEDURE_CATALOG") or "").upper()
    schema_name = (row.get("PROCEDURE_SCHEMA") or "").upper()
    is_builtin = (row.get("IS_BUILTIN") or "").upper()

    if owner in SYSTEM_OWNERS:
        return True
    if name.startswith(("SYSTEM$", "SNOWFLAKE$", "$")):
        return True
    if is_builtin == "Y":
        return True
    if catalog and catalog != database.upper():
        return True
    if schema_name and schema_name != current_schema.upper():
        return True
    return False


# ============================================================
# DEFINITION GENERATORS
# ============================================================

def generic_ddl_define(obj_type, name, db_name, schema, ddl_type=None):
    ddl_key = ddl_type or obj_type
    try:
        ddl = session.sql(
            f"SELECT GET_DDL('{ddl_key}', '{db_name}.{schema}.{name}')"
        ).collect()[0][0]

        ddl = replace_env(ddl)

        type_pattern = r"\s+".join(re.escape(w) for w in obj_type.split())
        ddl = re.sub(
            rf"CREATE\s+(OR\s+REPLACE\s+)?{type_pattern}\s+[^\s(]+",
            f"DEFINE {obj_type} {fq(name, schema)}",
            ddl,
            count=1,
            flags=re.IGNORECASE,
        )
        return ddl

    except Exception as e:
        return f"-- FAILED {obj_type} {fq(name, schema)} : {e}"


def stage_define(name, db_name, schema):
    try:
        rows = session.sql(f"SHOW STAGES IN SCHEMA {db_name}.{schema}").collect()
        for r in rows:
            row = {k.lower(): v for k, v in r.asDict().items()}
            if row.get("name") != name:
                continue

            lines = [f"DEFINE STAGE {fq(name, schema)}"]
            if row.get("url"):
                lines.append(f"URL = '{row['url']}'")
                if row.get("storage_integration"):
                    lines.append(f"STORAGE_INTEGRATION = {row['storage_integration']}")
            else:
                lines.append("DIRECTORY = ( ENABLE = TRUE )")
            if row.get("comment"):
                lines.append(f"COMMENT = '{row['comment']}'")
            return "\n".join(lines)

        return f"-- FAILED STAGE {fq(name, schema)}"
    except Exception as e:
        return f"-- FAILED STAGE {fq(name, schema)} : {e}"


def stream_define(name, db_name, schema):
    try:
        rows = session.sql(f"SHOW STREAMS IN SCHEMA {db_name}.{schema}").collect()
        for r in rows:
            if r["name"] == name:
                table_name = r.get("table_name", "")
                return f"DEFINE STREAM {fq(name, schema)}\nAS\nSELECT *\nFROM {replace_env(table_name)}"
        return f"-- FAILED STREAM {fq(name, schema)}"
    except Exception as e:
        return f"-- FAILED STREAM {fq(name, schema)} : {e}"


def sequence_define(name, db_name, schema):
    try:
        rows = session.sql(f"SHOW SEQUENCES IN SCHEMA {db_name}.{schema}").collect()
        for r in rows:
            row = {k.lower(): v for k, v in r.asDict().items()}
            if row.get("name") != name:
                continue
            lines = [f"DEFINE SEQUENCE {fq(name, schema)}"]
            if row.get("interval"):
                lines.append(f"INCREMENT = {row['interval']}")
            return "\n".join(lines)
        return f"-- FAILED SEQUENCE {fq(name, schema)}"
    except Exception as e:
        return f"-- FAILED SEQUENCE {fq(name, schema)} : {e}"


def file_format_define(name, db_name, schema):
    try:
        ddl = session.sql(
            f"SELECT GET_DDL('FILE FORMAT', '{db_name}.{schema}.{name}')"
        ).collect()[0][0]
        ddl = replace_env(ddl)
        ddl = re.sub(
            r"CREATE\s+(OR\s+REPLACE\s+)?FILE\s+FORMAT\s+[^\s]+",
            f"DEFINE FILE FORMAT {fq(name, schema)}",
            ddl,
            flags=re.IGNORECASE,
        )
        return ddl
    except Exception as e:
        return f"-- FAILED FILE FORMAT {fq(name, schema)} : {e}"


def procedure_define(name, db_name, schema, signature="()"):
    try:
        ddl = session.sql(
            f"SELECT GET_DDL('PROCEDURE', '{db_name}.{schema}.{name}{signature}')"
        ).collect()[0][0]
        ddl = replace_env(ddl)
        ddl = re.sub(
            r"CREATE\s+(OR\s+REPLACE\s+)?PROCEDURE\s+[^\s(]+",
            f"DEFINE PROCEDURE {fq(name, schema)}",
            ddl,
            flags=re.IGNORECASE,
        )
        return ddl
    except Exception as e:
        return f"-- FAILED PROCEDURE {fq(name, schema)} : {e}"


CUSTOM_HANDLERS = {
    "STAGE": stage_define,
    "STREAM": stream_define,
    "SEQUENCE": sequence_define,
    "FILE FORMAT": file_format_define,
}


def generate_definition(obj_type, name, db_name, schema, signature=None, ddl_type=None):
    if obj_type == "PROCEDURE":
        return procedure_define(name, db_name, schema, signature or "()")
    if obj_type in CUSTOM_HANDLERS:
        return CUSTOM_HANDLERS[obj_type](name, db_name, schema)
    return generic_ddl_define(obj_type, name, db_name, schema, ddl_type)


# ============================================================
# DATABASE & SCHEMA & ROLE DEFINITIONS
# ============================================================

def generate_database_definition(db_name):
    try:
        rows = session.sql(f"SHOW DATABASES LIKE '{db_name}'").collect()
        if not rows:
            return f"DEFINE DATABASE {TARGET_DB};"

        row = {k.lower(): v for k, v in rows[0].asDict().items()}
        lines = [f"DEFINE DATABASE {TARGET_DB}"]
        if row.get("comment"):
            lines.append(f"  COMMENT = '{row['comment']}'")
        if row.get("retention_time") and str(row["retention_time"]) != "1":
            lines.append(f"  DATA_RETENTION_TIME_IN_DAYS = {row['retention_time']}")
        lines.append(";")
        return "\n".join(lines)
    except Exception as e:
        return f"-- FAILED DATABASE {db_name} : {e}"


def generate_schema_definition(db_name, schema_name):
    try:
        rows = session.sql(f"SHOW SCHEMAS LIKE '{schema_name}' IN DATABASE {db_name}").collect()
        if not rows:
            return f"DEFINE SCHEMA {TARGET_DB}.{schema_name};"

        row = {k.lower(): v for k, v in rows[0].asDict().items()}
        lines = [f"DEFINE SCHEMA {TARGET_DB}.{schema_name}"]
        if row.get("comment"):
            lines.append(f"  COMMENT = '{row['comment']}'")
        if row.get("retention_time") and str(row["retention_time"]) != "1":
            lines.append(f"  DATA_RETENTION_TIME_IN_DAYS = {row['retention_time']}")
        if row.get("options") and "MANAGED ACCESS" in str(row.get("options", "")):
            lines.append("  WITH MANAGED ACCESS")
        lines.append(";")
        return "\n".join(lines)
    except Exception as e:
        return f"-- FAILED SCHEMA {db_name}.{schema_name} : {e}"


def generate_role_definitions(db_name):
    roles = set()
    try:
        rows = session.sql(f"SHOW GRANTS ON DATABASE {db_name}").collect()
        for r in rows:
            row = {k.lower(): v for k, v in r.asDict().items()}
            role = row.get("grantee_name", "")
            if role and role.upper() not in SYSTEM_OWNERS:
                roles.add(role)
    except Exception:
        pass

    for schema_name in DEV_SCHEMAS:
        try:
            rows = session.sql(f"SHOW GRANTS ON SCHEMA {db_name}.{schema_name}").collect()
            for r in rows:
                row = {k.lower(): v for k, v in r.asDict().items()}
                role = row.get("grantee_name", "")
                if role and role.upper() not in SYSTEM_OWNERS:
                    roles.add(role)
        except Exception:
            pass

    DATABASE_GRANT_TYPES = {"DATABASE"}
    SCHEMA_GRANT_TYPES = {"SCHEMA"}
    DATA_GRANT_TYPES = {"TABLE", "VIEW", "MATERIALIZED VIEW", "EXTERNAL TABLE", "DYNAMIC TABLE"}

    OPERATIONAL_GRANTS = [
        "EXECUTE TASK",
        "EXECUTE MANAGED TASK",
        "MONITOR EXECUTION",
    ]

    definitions = {}
    for role_name in sorted(roles):
        if role_name.upper() == ADMIN_ROLE:
            continue

        try:
            grants_rows = session.sql(f"SHOW GRANTS TO ROLE {role_name}").collect()

            db_grants = []
            schema_grants = []
            data_grants = []
            other_grants = []
            seen = set()

            for r in grants_rows:
                row = {k.lower(): v for k, v in r.asDict().items()}
                privilege = row.get("privilege", "")
                granted_on = row.get("granted_on", "")
                obj_name = row.get("name", "")
                obj_name = replace_env(obj_name) if obj_name else obj_name

                grant_key = f"{privilege}|{granted_on}|{obj_name}"
                if grant_key in seen:
                    continue
                seen.add(grant_key)

                grant_line = f"GRANT {privilege} ON {granted_on} {obj_name} TO ROLE {role_name};"

                if granted_on in DATABASE_GRANT_TYPES:
                    db_grants.append(grant_line)
                elif granted_on in SCHEMA_GRANT_TYPES:
                    schema_grants.append(grant_line)
                elif granted_on in DATA_GRANT_TYPES:
                    data_grants.append(grant_line)
                else:
                    other_grants.append(grant_line)

            role_cfg = ROLES_CONFIG.get(role_name, {})
            if role_cfg.get("create", False) or role_cfg.get("ownership", False):
                for op_grant in OPERATIONAL_GRANTS:
                    grant_line = f"GRANT {op_grant} ON ACCOUNT TO ROLE {role_name};"
                    grant_key = f"{op_grant}|ACCOUNT|"
                    if grant_key not in seen:
                        seen.add(grant_key)
                        other_grants.append(grant_line)

            lines = [f"DEFINE ROLE {role_name}", ""]

            if db_grants:
                lines.append("-- ===== DATABASE GRANTS =====")
                lines.extend(sorted(db_grants))
                lines.append("")

            if schema_grants:
                lines.append("-- ===== SCHEMA GRANTS =====")
                lines.extend(sorted(schema_grants))
                lines.append("")

            if data_grants:
                lines.append("-- ===== DATA GRANTS (Tables / Views) =====")
                lines.extend(sorted(data_grants))
                lines.append("")

            if other_grants:
                lines.append("-- ===== OPERATIONAL GRANTS =====")
                lines.extend(sorted(other_grants))
                lines.append("")

            definitions[role_name] = "\n".join(lines)
        except Exception as e:
            definitions[role_name] = f"-- FAILED ROLE {role_name} : {e}"

    return definitions


# ============================================================
# OBJECT DISCOVERY
# ============================================================

def discover_objects(db_name, schema):
    fqn = f"{db_name}.{schema}"
    objects = []
    dynamic_table_names = set()

    for obj_type, _folder, show_cmd, _uses_ddl, _ddl_override in OBJECT_REGISTRY:

        if obj_type == "PROCEDURE":
            try:
                proc_rows = session.sql(f"""
                    SELECT *
                    FROM {db_name}.INFORMATION_SCHEMA.PROCEDURES
                    WHERE PROCEDURE_SCHEMA = '{schema}'
                """).collect()

                for r in proc_rows:
                    row = {k.upper(): v for k, v in r.asDict().items()}
                    if is_system_procedure(row, db_name, schema):
                        continue
                    name = row["PROCEDURE_NAME"]
                    sig = row.get("ARGUMENT_SIGNATURE") or "()"
                    objects.append((name, obj_type, sig))
            except Exception as e:
                print(f"  SKIPPED PROCEDURES: {e}")
            continue

        if not show_cmd:
            continue

        try:
            rows = session.sql(show_cmd.format(fqn=fqn)).collect()
            for r in rows:
                name = r["name"]

                if obj_type == "DYNAMIC TABLE":
                    dynamic_table_names.add(name)
                elif obj_type == "TABLE" and name in dynamic_table_names:
                    continue

                objects.append((name, obj_type, None))
        except Exception as e:
            print(f"  SKIPPED {obj_type}: {e}")

    return objects


# ============================================================
# MAIN
# ============================================================

print(f"\nAll configured databases: {ALL_DB_NAMES}")
print(f"DEV databases (for object definitions): {DEV_DATABASES}")
print(f"Processing {len(DEV_SCHEMAS)} schema(s): {DEV_SCHEMAS}\n")

# Create ALL object-type folder structures
all_folders = sorted(set(FOLDER_MAP.values()) | {"databases", "schemas", "roles"})
for folder in all_folders:
    folder_path = TARGET_ROOT / folder
    folder_path.mkdir(parents=True, exist_ok=True)
    gitkeep = folder_path / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("")

print(f"Created folder structure: {TARGET_ROOT}")

skipped_count = 0

from config.config import DEFINITIONS_DIR

# ============================================================
# GENERATE SINGLE DATABASE TEMPLATE
# ============================================================
db_dir = DEFINITIONS_DIR / "databases"
db_dir.mkdir(parents=True, exist_ok=True)

db_file = db_dir / "database.sql"
db_sql = """{% if not is_default_target %}
DEFINE DATABASE {{ database }};
{% endif %}
"""
db_file.write_text(db_sql, encoding="utf-8")

# ============================================================
# GENERATE SINGLE SCHEMA TEMPLATE
# ============================================================
schema_dir = DEFINITIONS_DIR / "schemas"
schema_dir.mkdir(parents=True, exist_ok=True)

schema_file = schema_dir / "schemas.sql"
schema_sql = """{% if not is_default_target %}
{% for schema_name in schemas %}
DEFINE SCHEMA {{ database }}.{{ schema_name }};
{% endfor %}
{% endif %}
"""
schema_file.write_text(schema_sql, encoding="utf-8")
# --- Generate ROLE definitions (from DEV databases) ---
# print(f"\n--- Generating role definitions ---\n")
# all_role_defs = {}
# for db_name in DEV_DATABASES:
#     role_defs = generate_role_definitions(db_name)
#     all_role_defs.update(role_defs)

# for role_name, role_content in all_role_defs.items():
#     role_file = TARGET_ROOT / "roles" / f"{role_name}.sql"
#     if role_file.exists():
#         print(f"  SKIPPED (already exists): roles/{role_name}.sql")
#         skipped_count += 1
#     else:
#         role_file.write_text(role_content, encoding="utf-8")
#         print(f"  WROTE: roles/{role_name}.sql")

# print(f"\nTotal roles generated: {len(all_role_defs)}")

# --- Generate object definitions ONLY from DEV databases ---
total_objects = 0

for db_name in DEV_DATABASES:
    print(f"\n{'#'*60}")
    print(f"DATABASE: {db_name} (DEV)")
    print(f"{'#'*60}")

    for _current_schema in DEV_SCHEMAS:
        print(f"\n{'='*60}")
        print(f"SCHEMA: {db_name}.{_current_schema}")
        print(f"{'='*60}\n")

        objects = discover_objects(db_name, _current_schema)
        print(f"\nObjects found in {db_name}.{_current_schema}: {len(objects)}")
        total_objects += len(objects)

        print(f"\n--- Generating definitions for {db_name}.{_current_schema} ---\n")

        for name, obj_type, signature in objects:
            try:
                file_path = get_path(obj_type, name, db_name, _current_schema)

                if file_path.exists():
                    print(f"  SKIPPED (already exists): {file_path.relative_to(TARGET_ROOT)}")
                    skipped_count += 1
                    continue

                ddl_type = None
                for reg_type, _, _, _, reg_override in OBJECT_REGISTRY:
                    if reg_type == obj_type:
                        ddl_type = reg_override
                        break

                result = generate_definition(obj_type, name, db_name, _current_schema, signature, ddl_type)

                file_path.write_text(result, encoding="utf-8")
                print(f"  WROTE: {file_path.relative_to(TARGET_ROOT)}")

            except Exception as e:
                print(f"  FAILED {obj_type} {name}: {e}")

print(f"\n{'='*60}")
print(f"TOTAL OBJECTS ACROSS ALL DEV SCHEMAS: {total_objects}")
print(f"TOTAL SKIPPED (already existed): {skipped_count}")
print("DONE")
