from snowflake.snowpark.context import get_active_session
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True

session = get_active_session()

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

SYSTEM_OWNERS = {
    "SYSTEM",
    "SNOWFLAKE",
    "ACCOUNTADMIN",
    "ORGADMIN",
}

# ============================================================
# PATH SETUP
# ============================================================

SCRIPTS_DIR = ROOT
TARGET_ROOT = SCRIPTS_DIR / "ddl_scripts"
TARGET_ROOT.mkdir(parents=True, exist_ok=True)

print("DDL ROOT:", TARGET_ROOT)

# ============================================================
# FOLDER MAP
# ============================================================

FOLDER_MAP = {
    "TABLE": "tables",
    "DYNAMIC TABLE": "dynamic_tables",
    "VIEW": "views",
    "STAGE": "stages",
    "FILE FORMAT": "file_formats",
    "STREAM": "streams",
    "TASK": "tasks",
    "PROCEDURE": "procedures",
    "FUNCTION": "functions",
}

# ============================================================
# HELPERS
# ============================================================

def safe_query(sql):
    try:
        return session.sql(sql).collect()
    except Exception:
        return []


def replace_env(text, source_db, target_db):
    if not text:
        return text

    return re.sub(
        rf"\b{re.escape(source_db)}\b",
        target_db,
        text,
        flags=re.IGNORECASE,
    )


def get_path(obj_type, name, schema):
    folder = FOLDER_MAP.get(obj_type, "others")
    path = TARGET_ROOT / folder
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{name}.sql"


def fq(target_db, schema, name):
    return f"{target_db}.{schema}.{name}"


# ============================================================
# SYSTEM FILTER
# ============================================================

def is_system_procedure(row):
    owner = (row.get("OWNER") or "").upper()
    name = (row.get("PROCEDURE_NAME") or "").upper()
    catalog = (row.get("PROCEDURE_CATALOG") or "").upper()
    is_builtin = (row.get("IS_BUILTIN") or "").upper()

    if owner in SYSTEM_OWNERS:
        return True

    if name.startswith(("SYSTEM$", "SNOWFLAKE$", "$")):
        return True

    if is_builtin == "YES":
        return True

    if catalog and catalog != row.get("PROCEDURE_CATALOG", "").upper():
        return True

    return False


# ============================================================
# STAGE DDL
# ============================================================

def stage_ddl(source_db, target_db, name, schema):

    rows = safe_query(f"SHOW STAGES IN SCHEMA {source_db}.{schema}")

    for r in rows:
        row = {k.lower(): v for k, v in r.asDict().items()}

        if row["name"] != name:
            continue

        ddl = [f"CREATE OR REPLACE STAGE {fq(target_db, schema, name)}"]

        if row.get("url"):
            ddl.append(f"URL = '{row['url']}'")

            if row.get("storage_integration"):
                ddl.append(
                    f"STORAGE_INTEGRATION = {row['storage_integration']}"
                )
        else:
            ddl.append("DIRECTORY = ( ENABLE = TRUE )")

        if row.get("comment"):
            ddl.append(f"COMMENT = '{row['comment']}'")

        return "\n".join(ddl)

    return f"-- FAILED STAGE {name}"


# ============================================================
# GET DDL
# ============================================================

def get_ddl(
    source_db,
    target_db,
    obj_type,
    schema,
    name,
    signature=None,
):
    try:

        if obj_type == "STAGE":
            return stage_ddl(
                source_db,
                target_db,
                name,
                schema,
            )

        if obj_type == "PROCEDURE":
            if not signature:
                return f"-- SKIPPED PROCEDURE {name}: missing signature"

            identifier = f"{source_db}.{schema}.{name}{signature}"
        else:
            identifier = f"{source_db}.{schema}.{name}"

        ddl = session.sql(
            f"SELECT GET_DDL('{obj_type}', '{identifier}')"
        ).collect()[0][0]

        return replace_env(
            ddl,
            source_db,
            target_db,
        )

    except Exception as e:
        return f"-- FAILED {obj_type} {name}: {e}"


# ============================================================
# COLLECT OBJECTS
# ============================================================

objects = []

# Use dev branch databases and schemas for DDL extraction
_dev_branch = BRANCH_DATA.get("dev", {})
DEV_DATABASES = _dev_branch.get("sf_databases", [])
DEV_SCHEMAS = _dev_branch.get("sf_schemas", config.all_schemas)

for SOURCE_DB in DEV_DATABASES:
    TARGET_DB = SOURCE_DB

    print(f"\nProcessing database: {SOURCE_DB}")

    for schema in DEV_SCHEMAS:

        print(f"Processing schema: {schema}")

        # ---------------- DYNAMIC TABLES ----------------

        dyn = safe_query(
            f"SHOW DYNAMIC TABLES IN SCHEMA {SOURCE_DB}.{schema}"
        )

        dyn_names = set()

        for r in dyn:
            objects.append(
                (
                    SOURCE_DB,
                    TARGET_DB,
                    schema,
                    r["name"],
                    "DYNAMIC TABLE",
                    None,
                )
            )
            dyn_names.add(r["name"])

        # ---------------- TABLES ----------------

        for r in safe_query(
            f"SHOW TABLES IN SCHEMA {SOURCE_DB}.{schema}"
        ):
            if r["name"] not in dyn_names:
                objects.append(
                    (
                        SOURCE_DB,
                        TARGET_DB,
                        schema,
                        r["name"],
                        "TABLE",
                        None,
                    )
                )

        # ---------------- VIEWS ----------------

        for r in safe_query(
            f"SHOW VIEWS IN SCHEMA {SOURCE_DB}.{schema}"
        ):
            objects.append(
                (
                    SOURCE_DB,
                    TARGET_DB,
                    schema,
                    r["name"],
                    "VIEW",
                    None,
                )
            )

        # ---------------- STAGES ----------------

        for r in safe_query(
            f"SHOW STAGES IN SCHEMA {SOURCE_DB}.{schema}"
        ):
            objects.append(
                (
                    SOURCE_DB,
                    TARGET_DB,
                    schema,
                    r["name"],
                    "STAGE",
                    None,
                )
            )

        # ---------------- FILE FORMATS ----------------

        for r in safe_query(
            f"SHOW FILE FORMATS IN SCHEMA {SOURCE_DB}.{schema}"
        ):
            objects.append(
                (
                    SOURCE_DB,
                    TARGET_DB,
                    schema,
                    r["name"],
                    "FILE FORMAT",
                    None,
                )
            )

        # ---------------- STREAMS ----------------

        for r in safe_query(
            f"SHOW STREAMS IN SCHEMA {SOURCE_DB}.{schema}"
        ):
            objects.append(
                (
                    SOURCE_DB,
                    TARGET_DB,
                    schema,
                    r["name"],
                    "STREAM",
                    None,
                )
            )

        # ---------------- TASKS ----------------

        for r in safe_query(
            f"SHOW TASKS IN SCHEMA {SOURCE_DB}.{schema}"
        ):
            objects.append(
                (
                    SOURCE_DB,
                    TARGET_DB,
                    schema,
                    r["name"],
                    "TASK",
                    None,
                )
            )

        # ---------------- PROCEDURES ----------------

        proc_rows = safe_query(
            f"""
            SELECT *
            FROM {SOURCE_DB}.INFORMATION_SCHEMA.PROCEDURES
            WHERE PROCEDURE_SCHEMA = '{schema}'
            """
        )

        for r in proc_rows:

            row = {k.upper(): v for k, v in r.asDict().items()}

            if is_system_procedure(row):
                continue

            objects.append(
                (
                    SOURCE_DB,
                    TARGET_DB,
                    schema,
                    row["PROCEDURE_NAME"],
                    "PROCEDURE",
                    row.get("ARGUMENT_SIGNATURE"),
                )
            )


# ============================================================
# WRITE DDL
# ============================================================

print(f"\nTOTAL OBJECTS: {len(objects)}")

for (
    source_db,
    target_db,
    schema,
    name,
    obj_type,
    signature,
) in objects:

    ddl = get_ddl(
        source_db,
        target_db,
        obj_type,
        schema,
        name,
        signature,
    )

    file_path = get_path(obj_type, name, schema)

    try:
        file_path.write_text(ddl, encoding="utf-8")
        print(f"WROTE {schema} {obj_type}: {file_path}")

    except Exception as e:
        print(f"FAILED {schema} {obj_type} {name}: {e}")

print("DONE")