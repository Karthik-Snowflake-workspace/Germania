from pathlib import Path
import yaml

class ConfigLoader:
    """Load configuration from project_config.yml."""
    def __init__(self, config_file="project_config.yml"):
        # ----------------------------------------------------
        # Locate config directory
        # ----------------------------------------------------
        try:
            base_dir = Path(__file__).resolve().parent
        except NameError:
            current = Path.cwd().resolve()
            base_dir = None
            for parent in [current] + list(current.parents):
                candidate = parent / "config"
                if (candidate.exists() and (candidate / config_file).exists()):
                    base_dir = candidate
                    break

        if base_dir is None:
            raise RuntimeError(f"Could not locate '{config_file}'.")

        self.base_dir = base_dir
        self.config_file = base_dir / config_file

        # ----------------------------------------------------
        # Read configuration
        # ----------------------------------------------------
        if not self.config_file.exists():
            raise FileNotFoundError(self.config_file)

        with self.config_file.open("r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}

    @property
    def branch_data(self):
        return self._config.get("branch_data", {})

    @property
    def branch_sequence(self):
        return self._config.get("branch_sequence", [])

    @property
    def all_databases(self):
        databases = []
        b_data = self.branch_data
        
        if isinstance(b_data, dict):
            for branch_name, branch in b_data.items():
                if not branch or not isinstance(branch, dict):
                    continue
                for db in branch.get("sf_databases", []):
                    if db not in databases:
                        databases.append(db)
        return databases

    @property
    def all_schemas(self):
        schemas = []
        b_data = self.branch_data
        
        if isinstance(b_data, dict):
            for branch_name, branch in b_data.items():
                if not branch or not isinstance(branch, dict):
                    continue
                for schema in branch.get("sf_schemas", []):
                    if schema not in schemas:
                        schemas.append(schema)
        return schemas

    @property
    def dcm_project_name(self):
        return self._config.get("dcm_project_name", "")

    @property
    def dbt_dir(self):
        return self._config.get("dbt_dir", "")

    # ==========================================
    # NEW PROPERTIES ADDED TO FIX ATTRIBUTE ERROR
    # ==========================================
    @property
    def account_identifier(self):
        return self._config.get("snowflake_global", {}).get("account_identifier", "")

    @property
    def admin_role(self):
        return self._config.get("snowflake_global", {}).get("admin_role", "")

    @property
    def warehouse(self):
        return self._config.get("snowflake_global", {}).get("warehouse", "")
        
    @property
    def roles(self):
        return self._config.get("roles", {})


# ----------------------------------------------------
# Initialize Config and Expose Variables
# ----------------------------------------------------
config = ConfigLoader()

# Branch data
BRANCH_DATA = config.branch_data

# Derived
ALL_DATABASES = config.all_databases
ALL_SCHEMAS = config.all_schemas
DCM_PROJECT_NAME = config.dcm_project_name
DBT_DIR = config.dbt_dir


# ============================================================
# LOAD CONFIG
# ============================================================

config = ConfigLoader()

# Snowflake global
ACCOUNT_IDENTIFIER = config.account_identifier
ADMIN_ROLE = config.admin_role
WAREHOUSE = config.warehouse

# Roles
ROLES = config.roles

# Branch data
BRANCH_DATA = config.branch_data

# Derived
ALL_DATABASES = config.all_databases
ALL_SCHEMAS = config.all_schemas
DCM_PROJECT_NAME = config.dcm_project_name
DBT_DIR = config.dbt_dir

# ============================================================
# DIRECTORY STRUCTURE
# ============================================================

SCRIPTS_DIR = config.base_dir.parent

# logs/ (inside scripts)
LOGS_DIR = SCRIPTS_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# workspace/ (parent of scripts)
WORKSPACE_DIR = SCRIPTS_DIR.parent

# ------------------------------------------------------------
# Locate DCM project
# ------------------------------------------------------------

PROJECT_DIR = None

if DCM_PROJECT_NAME:
    for child in WORKSPACE_DIR.iterdir():
        if (
            child.is_dir()
            and child.name.lower() == DCM_PROJECT_NAME.lower()
        ):
            PROJECT_DIR = child.resolve()
            break

MANIFEST_FILE = PROJECT_DIR / "manifest.yml" if PROJECT_DIR else None

MACROS_DIR = None
DEFINITIONS_DIR = None

if PROJECT_DIR:
    MACROS_DIR = PROJECT_DIR / "sources" / "macros"
    MACROS_DIR.mkdir(parents=True, exist_ok=True)

    DEFINITIONS_DIR = PROJECT_DIR / "sources" / "definitions"
    DEFINITIONS_DIR.mkdir(parents=True, exist_ok=True)

# dbt project directory
DBT_PROJECT_DIR = None
if DBT_DIR:
    DBT_PROJECT_DIR = WORKSPACE_DIR / Path(DBT_DIR).name
    DBT_PROJECT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# DEBUG
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print("CONFIGURATION")
    print("=" * 60)

    print("Config File      :", config.config_file)
    print("Account          :", ACCOUNT_IDENTIFIER)
    print("Admin Role       :", ADMIN_ROLE)
    print("Warehouse        :", WAREHOUSE)
    print("Scripts Dir      :", SCRIPTS_DIR)
    print("Workspace Dir    :", WORKSPACE_DIR)
    print("Logs Dir         :", LOGS_DIR)
    print("Project Dir      :", PROJECT_DIR)
    print("Manifest         :", MANIFEST_FILE)
    print("Macros           :", MACROS_DIR)
    print("Definitions      :", DEFINITIONS_DIR)
    # print("dbt              :", DBT_PROJECT_DIR)

    print("\nBranches:")
    for branch_name, branch in BRANCH_DATA.items():
        print(f"  {branch_name}:")
        
        if not isinstance(branch, dict):
            print("    [Error: Branch data is empty or invalid]")
            continue
            
        print(f"    databases:  {branch.get('sf_databases')}")
        print(f"    schemas:    {branch.get('sf_schemas')}")
        print(f"    dcm_target: {branch.get('dcm_target')}")
        
        # ADD THIS LINE to see your branch-specific roles:
        print(f"    sf_roles:   {branch.get('sf_roles')}")
    for role, policy in ROLES.items():
        print(f"  {role}: {policy}")

    print("=" * 60)


# GUARANTEED DIRECTORY RESOLUTION FIX
if PROJECT_DIR is None:
    _target_name = DCM_PROJECT_NAME or "dcm_automation"
    PROJECT_DIR = (WORKSPACE_DIR / _target_name).resolve()
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    
    MANIFEST_FILE = PROJECT_DIR / "manifest.yml"
    MACROS_DIR = PROJECT_DIR / "sources" / "macros"
    MACROS_DIR.mkdir(parents=True, exist_ok=True)

    DEFINITIONS_DIR = PROJECT_DIR / "sources" / "definitions"
    DEFINITIONS_DIR.mkdir(parents=True, exist_ok=True)
