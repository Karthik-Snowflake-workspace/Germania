from pathlib import Path
import sys
import yaml

sys.dont_write_bytecode = True

# ============================================================
# LOAD CONFIGURATION
# ============================================================
ROOT = Path.cwd().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib
import config.config as cfg
importlib.reload(cfg)

config = cfg.config
PROJECT_DIR = cfg.PROJECT_DIR
MANIFEST_FILE = cfg.MANIFEST_FILE
LOGS_DIR = cfg.LOGS_DIR

# ============================================================
# YAML DUMPER
# ============================================================
class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True

# ============================================================
# BUILD MANIFEST
# ============================================================
BRANCH_DATA = config.branch_data
ACCOUNT_IDENTIFIER = config.account_identifier
ADMIN_ROLE = config.admin_role
WAREHOUSE = config.warehouse
if not config.dcm_project_name:
    raise RuntimeError("dcm_project_name must be defined in project_config.yml")
DCM_PROJECT_NAME = config.dcm_project_name.upper()

# 1. Find the target configuration (the metadata hub)
target_config = {}
for branch, cfg_data in BRANCH_DATA.items():
    if isinstance(cfg_data, dict) and cfg_data.get("is_default_target", False):
        target_config = cfg_data
        break

if not target_config:
    raise RuntimeError("No branch with is_default_target: true found in project_config.yml")

# 2. Dynamically pull the database (e.g., CICD_METADATA)
sf_databases = target_config.get("sf_databases", [])
if not sf_databases:
    raise RuntimeError("sf_databases must be defined for the metadata target in config.")
metadata_db = sf_databases[0].upper()

# 3. Dynamically pull the schema (falls back to DCM_CONFIG if not explicitly set in YAML)
metadata_schema = target_config.get("dcm_schema", "DCM_CONFIG").upper()

targets = {}
configurations = {}
default_target = None

for branch_name, branch_cfg in BRANCH_DATA.items():
    if not isinstance(branch_cfg, dict):
        continue

    dcm_target = branch_cfg.get("dcm_target")
    if not dcm_target:
        continue
        
    environment = branch_name
    env_suffix = f"_{environment}"
    
    # Construct project_name like CICD_METADATA.DCM_CONFIG.DCM_AUTOMATION_CICD
    project_name = f"{metadata_db}.{metadata_schema}.{DCM_PROJECT_NAME}_{environment.upper()}"
    
    database = branch_cfg.get("sf_databases", [""])[0] if branch_cfg.get("sf_databases") else ""
    schemas = branch_cfg.get("sf_schemas", [])
    
    # Map roles (e.g., DBA_ADMIN -> DBA_ADMIN_CICD)
    mapped_roles = {}
    for base_role in config.roles.keys():
        for sf_role in branch_cfg.get("sf_roles", []):
            if sf_role.upper().startswith(base_role.upper()):
                mapped_roles[base_role] = sf_role
                break
                
    # Admin role is referenced via project_owner_role in templates, no env-suffix mapping needed
    
    # Use is_default_target flag from config to determine the default
    is_default = branch_cfg.get("is_default_target", False)
    if is_default:
        default_target = dcm_target

    # 1. Build targets dictionary
    targets[dcm_target] = {
        "account_identifier": ACCOUNT_IDENTIFIER,
        "project_name": project_name,
        "project_owner": ADMIN_ROLE,
        "templating_config": environment
    }
    
    # 2. Build configurations dictionary
    configurations[environment] = {
        "environment": environment,
        "env_suffix": env_suffix,
        "database": database,
        "schemas": schemas,
        "project_name": project_name,
        "project_owner": ADMIN_ROLE,
        "roles": mapped_roles,
        "is_default_target": is_default
    }

if not default_target:
    raise RuntimeError("No branch with is_default_target: true found in project_config.yml")

# Assemble final manifest structure
manifest = {
    "manifest_version": 2,
    "type": "DCM_PROJECT",
    "default_target": default_target,
    "targets": targets,
    "templating": {
        "defaults": {
            "project_owner_role": ADMIN_ROLE,
            "warehouse": WAREHOUSE
        },
        "configurations": configurations
    }
}

# ============================================================
# WRITE MANIFEST
# ============================================================
if MANIFEST_FILE:
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        # sort_keys=False preserves the order in which we built the dictionaries
        yaml.dump(manifest, f, Dumper=NoAliasDumper, sort_keys=False, default_flow_style=False)
        
    print("=" * 60)
    print("Manifest generated successfully.")
    print(f"Output: {MANIFEST_FILE.resolve()}")
    print("=" * 60)
else:
    print("Error: MANIFEST_FILE path not resolved. Please check config directory structure.")