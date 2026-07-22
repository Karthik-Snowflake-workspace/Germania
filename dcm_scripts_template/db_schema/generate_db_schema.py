
from pathlib import Path
import sys
import importlib

sys.dont_write_bytecode = True

# ============================================================
# LOAD CONFIGURATION
# ============================================================

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
ROLES = config.roles
ADMIN_ROLE = config.admin_role


# ============================================================
# OUTPUT LOCATION
# ============================================================

OUTPUT_FILE = LOGS_DIR / "generate_databases.sql"


# ============================================================
# PRIVILEGES
# ============================================================

SCHEMA_CREATE_GRANTS = [
    "CREATE TABLE",
    "CREATE VIEW",
    "CREATE DYNAMIC TABLE",
    "CREATE STAGE",
    "CREATE STREAM",
    "CREATE TASK",
    "CREATE FILE FORMAT",
    "CREATE PROCEDURE",
    "CREATE FUNCTION",
    "CREATE DCM PROJECT",
]


# ============================================================
# GENERATE SQL
# ============================================================

sql = []

sql.append("-- ====================================================")
sql.append("-- DATABASE AND SCHEMA CREATION")
sql.append("-- ====================================================")
sql.append("")

# ============================================================
# ADMIN ROLE
# ============================================================

sql.append(f"USE ROLE {ADMIN_ROLE};")
sql.append("")


# ============================================================
# CREATE ROLES
# ============================================================

sql.append("-- ====================================================")
sql.append("-- CREATE ROLES")
sql.append("-- ====================================================")
sql.append("")

# 1. Collect all unique roles across all branches
all_roles_to_create = set()
for branch_name, branch_info in BRANCH_DATA.items():
    if isinstance(branch_info, dict):
        for role in branch_info.get("sf_roles", []):
            all_roles_to_create.add(role)

# 2. Generate CREATE statements for all collected roles
for role in sorted(list(all_roles_to_create)):
    sql.append(f"CREATE ROLE IF NOT EXISTS {role};")

    if role.upper() != ADMIN_ROLE.upper():
        sql.append(f"GRANT ROLE {role} TO ROLE {ADMIN_ROLE};")

sql.append("")


# ============================================================
# CREATE DATABASES AND SCHEMAS PER BRANCH
# ============================================================

for branch_name, branch in BRANCH_DATA.items():

    databases = branch.get("sf_databases", [])
    schemas = branch.get("sf_schemas", [])
    branch_roles = branch.get("sf_roles", list(ROLES.keys()))

    sql.append("-- ====================================================")
    sql.append(f"-- BRANCH: {branch_name}")
    sql.append("-- ====================================================")
    sql.append("")

    for db_name in databases:

        sql.append(f"CREATE DATABASE IF NOT EXISTS {db_name};")

        for schema in schemas:
            sql.append(
                f"CREATE SCHEMA IF NOT EXISTS {db_name}.{schema};"
            )

        sql.append("")

    # ============================================================
    # GRANTS PER ROLE FOR THIS BRANCH
    # ============================================================

    for role in branch_roles:

        policy = {}
        for base_role, base_policy in ROLES.items():
            if role.upper().startswith(base_role.upper()):
                policy = base_policy
                break

        for db_name in databases:

            sql.append(
                f"GRANT USAGE ON DATABASE "
                f"{db_name} TO ROLE {role};"
            )

            if policy.get("create"):
                sql.append(
                    f"GRANT CREATE SCHEMA ON DATABASE "
                    f"{db_name} TO ROLE {role};"
                )

            for schema in schemas:

                full_schema = f"{db_name}.{schema}"

                sql.append(
                    f"GRANT USAGE ON SCHEMA "
                    f"{full_schema} TO ROLE {role};"
                )

                if policy.get("create"):
                    for privilege in SCHEMA_CREATE_GRANTS:
                        sql.append(
                            f"GRANT {privilege} ON SCHEMA "
                            f"{full_schema} TO ROLE {role};"
                        )

                if policy.get("read"):
                    sql.append(
                        f"GRANT SELECT ON ALL TABLES IN SCHEMA "
                        f"{full_schema} TO ROLE {role};"
                    )
                    sql.append(
                        f"GRANT SELECT ON FUTURE TABLES IN SCHEMA "
                        f"{full_schema} TO ROLE {role};"
                    )
                    sql.append(
                        f"GRANT SELECT ON ALL VIEWS IN SCHEMA "
                        f"{full_schema} TO ROLE {role};"
                    )
                    sql.append(
                        f"GRANT SELECT ON FUTURE VIEWS IN SCHEMA "
                        f"{full_schema} TO ROLE {role};"
                    )

        sql.append("")


# ============================================================
# WRITE SQL
# ============================================================

OUTPUT_FILE.write_text(
    "\n".join(sql),
    encoding="utf-8"
)

print("=" * 60)
print("Database and grants SQL generated successfully.")
print(f"Output: {OUTPUT_FILE.resolve()}")
print("=" * 60)
