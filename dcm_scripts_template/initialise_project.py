# DCM automation pipeline runner with external session support (branch-based config)
# Co-authored with CoCo
import sys
import importlib.util
from pathlib import Path

sys.dont_write_bytecode = True

# ============================================================
# LOCATE SCRIPTS DIRECTORY
# ============================================================

current = Path(__file__).resolve().parent
scripts_dir = None

for directory in [current] + list(current.parents):
    if (directory / "config").is_dir() and (directory / "db_schema").is_dir():
        scripts_dir = directory
        break

if scripts_dir is None:
    raise RuntimeError(
        f"Could not locate the directory containing 'config' and 'db_schema'. Scanned anchor: {current}"
    )

# ============================================================
# PYTHON PATH
# ============================================================

if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

# ============================================================
# LOAD CONFIG
# ============================================================

import importlib
import config.config as cfg

importlib.reload(cfg)

config = cfg.config
LOGS_DIR = cfg.LOGS_DIR
PROJECT_DIR = cfg.PROJECT_DIR

# ============================================================
# PATHS
# ============================================================

DCM_PROJECT_NAME = config.dcm_project_name
SCRIPT_DIR = scripts_dir

LOGS_DIR = SCRIPT_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

PHASE1_SQL_OUTPUT = LOGS_DIR / "generate_databases.sql"
CREATE_DCM_PROJECTS_SQL = LOGS_DIR / "create_dcm_projects.sql"

print("=" * 60)
print(f"Scripts Directory : {SCRIPT_DIR}")
print(f"Logs Directory    : {LOGS_DIR}")
print("=" * 60)

# ============================================================
# SQL EXECUTION
# ============================================================

def execute_sql_file(sql_path: Path, session):

    if session is None:
        print("No Snowpark session available.")
        return False

    if not sql_path.exists():
        print(f"Missing SQL file: {sql_path}")
        return False

    sql_text = sql_path.read_text(encoding="utf-8")

    statements = []
    buffer = []

    for line in sql_text.splitlines():
        if line.strip().startswith("--"):
            continue

        buffer.append(line)

        if ";" in line:
            statements.append("\n".join(buffer).strip())
            buffer = []

    if buffer:
        statements.append("\n".join(buffer).strip())

    executed = 0
    errors = 0

    for stmt in statements:
        stmt = "\n".join(
            l for l in stmt.splitlines()
            if not l.strip().startswith("--")
        ).strip()

        if not stmt:
            continue

        try:
            session.sql(stmt).collect()
            executed += 1
        except Exception as e:
            errors += 1
            print(f"SQL Error: {e}")
            print(stmt[:150])

    print(f"Executed : {executed}")
    print(f"Errors   : {errors}")

    return errors == 0


# ============================================================
# RUN PYTHON SCRIPT
# ============================================================

def run_python_script(script_path: Path):

    spec = importlib.util.spec_from_file_location(
        script_path.stem,
        script_path,
    )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if hasattr(module, "main"):
        module.main()

# ============================================================
# PIPELINE CONFIGURATION
# ============================================================

EXECUTION_ORDER = [
    {
        "phase": "PHASE 1 : INFRASTRUCTURE",
        "scripts": [
            scripts_dir / "db_schema" / "generate_db_schema.py",
            scripts_dir / "dcm" / "dcm_project.py",
        ],
        "post_sql": [
            PHASE1_SQL_OUTPUT,
            CREATE_DCM_PROJECTS_SQL,
        ],
    },
    {
        "phase": "PHASE 2 : DCM SETUP",
        "scripts": [
            scripts_dir / "dcm" / "dcm_manifest.py",
            scripts_dir / "dcm" / "dcm_files.py",
            scripts_dir / "dcm" / "dcm_macros.py",
        ],
    },
    {
        "phase": "PHASE 3 : DDL EXTRACTION",
        "scripts": [],
    },
]

# ============================================================
# RUN PIPELINE
# ============================================================

def run_pipeline(phases=None, stop_on_error=False):

    total = 0
    passed = 0
    failed = 0
    skipped = 0

    print("=" * 60)
    print("DCM AUTOMATION PIPELINE")
    print("=" * 60)

    session = None

    # 1. Attempt internal native lookup first
    try:
        from snowflake.snowpark.context import get_active_session
        session = get_active_session()
        print("Snowpark session active via internal context")
    except Exception:
        # 2. External Runner Strategy using OIDC payload
        try:
            from snowflake.snowpark import Session
            import os
            import tempfile

            if "SNOWFLAKE_USER" in os.environ:
                del os.environ["SNOWFLAKE_USER"]

            target_token = os.environ.get("SNOWFLAKE_TOKEN")

            if target_token:
                with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as tf:
                    tf.write(target_token)
                    token_path = tf.name

                connection_config = {
                    "account": os.environ.get("SNOWFLAKE_ACCOUNT"),
                    "role": os.environ.get("SNOWFLAKE_ROLE"),
                    "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE"),
                    "database": os.environ.get("SNOWFLAKE_DATABASE"),
                    "schema": os.environ.get("SNOWFLAKE_SCHEMA"),
                    "authenticator": "WORKLOAD_IDENTITY",
                    "workload_identity_provider": "OIDC",
                    "token_file_path": token_path
                }

                session = Session.builder.configs(connection_config).getOrCreate()
                print("Snowpark session initialized via GitHub OIDC runner context")

                try:
                    os.unlink(token_path)
                except Exception:
                    pass
            else:
                print("OIDC Token variable 'SNOWFLAKE_TOKEN' is empty. Skipping external session.")
        except Exception as err:
            print(f"Unable to establish external Snowpark session: {err}")

    for index, phase in enumerate(EXECUTION_ORDER):

        if phases and index not in phases:
            continue

        print("\n" + "=" * 60)
        print(phase["phase"])
        print("=" * 60)

        # ----------------------------------------------------
        # PYTHON SCRIPTS
        # ----------------------------------------------------
        for script in phase["scripts"]:
            total += 1

            if not script.exists():
                skipped += 1
                print(f"SKIPPED : {script.name}")
                continue

            print(f"Running : {script.name}")

            try:
                run_python_script(script)
                passed += 1
                print("Success")
            except Exception as e:
                failed += 1
                print(f"Failed : {script.name}")
                print(str(e))

                if stop_on_error:
                    return False

        # ----------------------------------------------------
        # SQL FILES
        # ----------------------------------------------------
        for sql_file in phase.get("post_sql", []):
            print(f"Executing SQL : {sql_file.name}")

            try:
                if execute_sql_file(sql_file, session):
                    print("Success")
                else:
                    failed += 1
                    if stop_on_error:
                        return False
            except Exception as e:
                failed += 1
                print(e)
                if stop_on_error:
                    return False

    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"Total   : {total}")
    print(f"Passed  : {passed}")
    print(f"Failed  : {failed}")
    print(f"Skipped : {skipped}")
    print("=" * 60)

    return failed == 0


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--phase")
    parser.add_argument("--stop-on-error", action="store_true")

    args, _ = parser.parse_known_args()
    phases = None

    if args.phase:
        phases = [
            int(x.strip())
            for x in args.phase.split(",")
        ]

    success = run_pipeline(
        phases=phases,
        stop_on_error=args.stop_on_error,
    )

    sys.exit(0 if success else 1)
