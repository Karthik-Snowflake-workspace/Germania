from pathlib import Path
import sys
import yaml

sys.dont_write_bytecode = True

# ============================================================
# LOAD DBT CONFIG
# ============================================================

# Locate the config file in the same directory as this script (cwd in workspace kernel)
SCRIPT_DIR = Path.cwd().resolve()
DBT_CONFIG_FILE = SCRIPT_DIR / "project_configure_dbt.yml"

if not DBT_CONFIG_FILE.exists():
    # Fallback: walk up to find it
    current = SCRIPT_DIR
    for _ in range(10):
        candidate = current / "project_configure_dbt.yml"
        if candidate.exists():
            DBT_CONFIG_FILE = candidate
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

if not DBT_CONFIG_FILE.exists():
    print("ERROR: project_configure_dbt.yml not found.")
    sys.exit(1)

print(f"Using config: {DBT_CONFIG_FILE}")

with open(DBT_CONFIG_FILE, "r", encoding="utf-8") as f:
    dbt_config = yaml.safe_load(f)

# ============================================================
# CONFIG
# ============================================================

SNOWFLAKE_GLOBAL = dbt_config.get("snowflake_global", {})
DBT_GLOBAL = dbt_config.get("dbt_global", {})
BRANCH_DATA = dbt_config.get("branch_data", {})

ACCOUNT_IDENTIFIER = SNOWFLAKE_GLOBAL.get("account_identifier", "")
DEFAULT_WAREHOUSE = SNOWFLAKE_GLOBAL.get("warehouse", "")
DEFAULT_THREADS = DBT_GLOBAL.get("threads", 4)
PROJECT_NAME = DBT_GLOBAL.get("project_name", "dcm_dbt_cicd")

# Find the default target branch (is_default_target: true)
default_target = None
for branch_name, branch_cfg in BRANCH_DATA.items():
    if isinstance(branch_cfg, dict) and branch_cfg.get("is_default_target", False):
        default_target = branch_cfg.get("dbt_target", branch_name)
        break

if not default_target:
    default_target = next(iter(BRANCH_DATA)) if BRANCH_DATA else "dev"

# Output profiles.yml OUTSIDE dcm_scripts_template, in the project_name folder
# Navigate from dcm_scripts_template/dbt/ -> dcm_scripts_template/ -> workspace root
# Then write to workspace_root/project_name/profiles.yml
WORKSPACE_ROOT = SCRIPT_DIR.parent.parent
DBT_PROJECT_DIR = WORKSPACE_ROOT / PROJECT_NAME
PROFILES_FILE = DBT_PROJECT_DIR / "profiles.yml"

# Use the profile name from config
PROFILE_NAME = DBT_GLOBAL.get("profile", PROJECT_NAME)

# ============================================================
# GENERATE PROFILES.YML
# ============================================================

def main():

    if not BRANCH_DATA:
        print("No branch_data defined in project_configure_dbt.yml")
        return

    lines = [
        f"{PROFILE_NAME}:",
        f"  target: {default_target}",
        "",
        "  outputs:",
        "",
    ]

    for branch_name, branch in BRANCH_DATA.items():
        if not isinstance(branch, dict):
            continue

        dbt_target = branch.get("dbt_target", branch_name)
        # Support both field naming conventions
        user = branch.get("user", branch.get("sf_user", ""))
        sf_roles = branch.get("sf_roles", [])
        role = branch.get("role", sf_roles[0] if sf_roles else "")
        database = branch.get("database", branch.get("dbt_database", ""))
        warehouse = branch.get("warehouse", branch.get("dbt_warehouse", DEFAULT_WAREHOUSE))
        schema = branch.get("schema", branch.get("dbt_schema", "PUBLIC"))

        if not database:
            continue

        lines.extend([
            f"    {dbt_target}:",
            "      type: snowflake",
            f"      account: {ACCOUNT_IDENTIFIER}",
            f"      user: {user}",
            f"      role: {role}",
            f"      database: {database}",
            f"      warehouse: {warehouse}",
            f"      schema: {schema}",
            f"      threads: {DEFAULT_THREADS}",
            "      client_session_keep_alive: false",
            "",
        ])

    DBT_PROJECT_DIR.mkdir(parents=True, exist_ok=True)

    PROFILES_FILE.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print("=" * 60)
    print("profiles.yml generated successfully.")
    print("=" * 60)
    print(f"DBT Project    : {DBT_PROJECT_DIR}")
    print(f"Profiles File  : {PROFILES_FILE}")
    print(f"Profile Name   : {PROFILE_NAME}")
    print(f"Default Target : {default_target}")

    print("\nConfigured Targets")
    print("-" * 60)

    for branch_name, branch in BRANCH_DATA.items():
        if not isinstance(branch, dict):
            continue

        dbt_target = branch.get("dbt_target", branch_name)
        database = branch.get("database", branch.get("dbt_database", ""))
        sf_roles = branch.get("sf_roles", [])
        role = branch.get("role", sf_roles[0] if sf_roles else "N/A")
        schema = branch.get("schema", branch.get("dbt_schema", "PUBLIC"))

        if not database:
            continue

        print(
            f"{dbt_target:<10}"
            f" Database={database:<25}"
            f" Role={role:<30}"
            f" Schema={schema}"
        )

    print("=" * 60)
    print("Done.")
    print("=" * 60)


main()
