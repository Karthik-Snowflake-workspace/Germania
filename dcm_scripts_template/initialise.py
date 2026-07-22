
import sys
import yaml
from pathlib import Path

# ============================================================
# LOCATE SCRIPTS DIRECTORY
# ============================================================
current = Path.cwd().resolve()
scripts_dir = None
for directory in [current] + list(current.parents):
    if (directory / "config").is_dir() and (directory / "db_schema").is_dir():
        scripts_dir = directory
        break

if scripts_dir is None:
    raise RuntimeError("Could not locate the 'scripts' directory.")

# Safely extract the DCM project name from project_config.yml
DCM_PROJECT_NAME = None
config_yaml_path = scripts_dir / "config" / "project_config.yml"

if config_yaml_path.exists():
    with open(config_yaml_path, "r", encoding="utf-8") as f:
        parsed_yaml = yaml.safe_load(f) or {}
        # Extract dcm_dir from branch_data (common across branches)
        branch_data = parsed_yaml.get("branch_data", {})
        for branch in branch_data.values():
            if "dcm_dir" in branch:
                DCM_PROJECT_NAME = branch["dcm_dir"]
                break

if not DCM_PROJECT_NAME:
    raise RuntimeError("Could not parse 'dcm_dir' from branch_data in project_config.yml")

# ============================================================
# CREATE DCM FOLDER STRUCTURE FIRST
# ============================================================
base_project_dir = scripts_dir.parent / DCM_PROJECT_NAME

if not base_project_dir.exists():
    print(f"Creating DCM folder structure under: {base_project_dir}")
    base_project_dir.mkdir(parents=True, exist_ok=True)

def create_dcm_structure(base_dir):
    """Creates the DCM project folder structure under base_dir."""
    import os
    dirs = [
        base_dir,
        os.path.join(base_dir, "sources"),
        os.path.join(base_dir, "sources", "definitions"),
        os.path.join(base_dir, "sources", "macros"),
        os.path.join(base_dir, "out"),
        os.path.join(base_dir, "out", "analyze"),
        os.path.join(base_dir, "out", "analyze", "analyze_dependencies_output"),
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

    manifest_root = os.path.join(base_dir, "manifest.yml")
    if not os.path.exists(manifest_root):
        with open(manifest_root, "w") as f:
            pass
        print(f"Created DCM folder structure under: {base_dir}")
    else:
        print(f"DCM folder structure already exists at: {base_project_dir}. Skipping creation.")


create_dcm_structure(base_project_dir)

# ============================================================
# PYTHON PATH & LOAD CONFIG
# ============================================================
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

import importlib
import config.config as cfg
importlib.reload(cfg)

config = cfg.config
LOGS_DIR = cfg.LOGS_DIR
PROJECT_DIR = cfg.PROJECT_DIR

# ============================================================
# PATHS
# ============================================================

WORKSPACE_DIR = cfg.WORKSPACE_DIR
_project_dir = WORKSPACE_DIR / DCM_PROJECT_NAME
_project_dir.mkdir(parents=True, exist_ok=True)
(_project_dir / "sources" / "definitions").mkdir(parents=True, exist_ok=True)
(_project_dir / "sources" / "macros").mkdir(parents=True, exist_ok=True)
(_project_dir / "out" / "analyze" / "analyze_dependencies_output").mkdir(parents=True, exist_ok=True)

# Create placeholder files if missing
for _f in [
    _project_dir / "manifest.yml",
    _project_dir / "out" / "analyze" / "analyze_dependencies.json",
    _project_dir / "out" / "analyze" / "analyze_dependencies_output" / "manifest.yml",
]:
    if not _f.exists():
        _f.touch()

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
        print(" No Snowpark session available.")
        return False

    if not sql_path.exists():
        print(f" Missing SQL file: {sql_path}")
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
# PIPELINE
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
        "scripts": [
            scripts_dir / "dcm" / "ddl_scripts.py",
        ],
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

    try:
        from snowflake.snowpark.context import get_active_session
        session = get_active_session()
        print("Snowpark session active")

    except Exception as e:
        print(f"Snowpark session unavailable: {e}")

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
