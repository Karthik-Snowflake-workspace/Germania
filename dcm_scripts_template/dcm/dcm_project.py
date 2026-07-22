from pathlib import Path
import sys
import importlib

sys.dont_write_bytecode = True

ROOT = Path.cwd().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config.config as cfg
importlib.reload(cfg)

config = cfg.config
LOGS_DIR = cfg.LOGS_DIR

# ============================================================
# CONFIG
# ============================================================
BRANCH_DATA = config.branch_data
ADMIN_ROLE = config.admin_role.upper()

# Find the branch where is_default_target is true (to act as the metadata hub)
target_config = {}
for branch_name, branch_cfg in BRANCH_DATA.items():
    if isinstance(branch_cfg, dict) and branch_cfg.get("is_default_target", False):
        target_config = branch_cfg
        break

if not target_config:
    raise RuntimeError("No branch with is_default_target: true found in project_config.yml")

# ============================================================
# DYNAMIC VARIABLES (No hardcoding)
# ============================================================
sf_databases = target_config.get("sf_databases", [])
if not sf_databases:
    raise RuntimeError("sf_databases must be defined for the metadata target in project_config.yml.")

metadata_db = sf_databases[0].upper()
# Uses "DCM_CONFIG" as a safe fallback just in case it isn't explicitly defined in YAML
metadata_schema = target_config.get("dcm_schema", "DCM_CONFIG").upper()

OUTPUT_FILE = LOGS_DIR / "create_dcm_projects.sql"

# ============================================================
# GENERATE SQL
# ============================================================
sql = []

sql.append("-- ====================================================")
sql.append("-- CREATE DCM PROJECTS FOR ALL ENVIRONMENTS")
sql.append("-- ====================================================")
sql.append("")

sql.append(f"USE ROLE {ADMIN_ROLE};")
sql.append("")

sql.append(f"USE DATABASE {metadata_db};")
sql.append(f"CREATE SCHEMA IF NOT EXISTS {metadata_db}.{metadata_schema};")
sql.append(f"USE SCHEMA {metadata_db}.{metadata_schema};")
sql.append("")

# Loop through all branches to create their specific DCM targets
for branch_name, branch_cfg in BRANCH_DATA.items():
    if not isinstance(branch_cfg, dict):
        continue

    dcm_target = branch_cfg.get("dcm_target")
    dcm_dir = branch_cfg.get("dcm_dir")
    project_name_from_cfg = branch_cfg.get("project_name")

    sql.append(f"-- Project for {branch_name.upper()} environment")
    
    # 1. HIGHEST PRIORITY: If project_name is explicitly defined in YAML, use it exactly
    if project_name_from_cfg:
        sql.append(f"CREATE DCM PROJECT IF NOT EXISTS {project_name_from_cfg};")
        
    # 2. ALL ENVIRONMENTS (Including metadata hub): Construct using dcm_dir + branch_name
    elif dcm_dir:
        project_name = f"{dcm_dir.upper()}_{branch_name.upper()}"
        sql.append(f"CREATE DCM PROJECT IF NOT EXISTS {metadata_db}.{metadata_schema}.{project_name};")
        
    # 3. Fallback behavior if dcm_dir is missing
    elif dcm_target:
        sql.append(f"CREATE DCM PROJECT IF NOT EXISTS {metadata_db}.{metadata_schema}.{dcm_target.upper()};")
    
    sql.append("")

# ============================================================
# WRITE SQL
# ============================================================
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(sql))

print("=" * 60)
print("DCM Project creation SQL generated successfully.")
print(f"Output: {OUTPUT_FILE.resolve()}")
print("=" * 60)