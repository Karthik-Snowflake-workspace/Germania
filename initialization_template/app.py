import streamlit as st
import os
import sys
import yaml
import requests
import subprocess
import shutil
import tempfile
import time
import github
from github import Github, GithubException
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import snowflake.connector
except ImportError:
    snowflake = None

# ==========================================================
# STREAMLIT PAGE LAYOUT & CONFIGURATION
# ==========================================================
st.set_page_config(
    page_title="Enterprise GitOps & Snowflake Onboarding Portal",
    layout="wide"
)

st.title("🚀 Enterprise GitOps & Snowflake Onboarding Portal")
st.caption("Sequential Orchestration & DCM Delivery Engine for Dynamic Multi-Branch Snowflake Infrastructure.")

# ==========================================================
# 📋 DECOUPLED PIPELINE WORKFLOW BLUEPRINT GENERATORS
# ==========================================================

def generate_dcm_action_yml():
    """Generates the reusable composite module for Snowflake DCM tasks with manifest guards."""
    return """name: 'Snowflake DCM Execution Module'
description: 'Modular core engine managing Snowflake database infrastructure changes via DCM'
inputs:
  dcm_dir:
    description: 'Path directory holding dcm configurations'
    required: true
  dcm_target:
    description: 'Target profile environment label'
    required: true
  action_type:
    description: 'Execution context mode (plan or deploy)'
    required: true
runs:
  using: "composite"
  steps:
    - name: Setup Snowflake CLI (OIDC)
      uses: snowflakedb/snowflake-cli-action@v2.0
      with:
        use-oidc: true
    - name: Execute Targeted DCM Operations
      shell: bash
      run: |
        cd ${{ inputs.dcm_dir }}
        if [ ! -f "manifest.yml" ] || [ ! -s "manifest.yml" ]; then
          echo "⚠️ manifest.yml not found or empty in ${{ inputs.dcm_dir }}. Skipping DCM step until orchestration runs."
          exit 0
        fi
        if [ "${{ inputs.action_type }}" = "plan" ]; then
          echo "Processing structural change mappings execution dry-run..."
          snow dcm plan --target ${{ inputs.dcm_target }} -x
        else
          echo "LIVE: Pushing structural modifications directly into active database target..."
          snow dcm deploy --target ${{ inputs.dcm_target }} -x
        fi
"""

def generate_manual_init_yml():
    """Generates sequential orchestration workflow that ignores dcm_automation changes to prevent recursive loop."""
    return """name: "Snowflake Script Orchestration & DCM Matrix"
on:
  push:
    branches:
      - dcm_project
    paths:
      - 'Projects/**'
      - 'dcm_scripts_template/**'
      - 'config/**'
      - 'helper_scripts/**'
  workflow_dispatch:

concurrency:
  group: orchestration-${{ github.ref }}
  cancel-in-progress: true

permissions:
  id-token: write
  contents: write

jobs:
  orchestrate-and-deploy:
    runs-on: ubuntu-latest
    environment: ${{ github.ref_name == 'main' && 'main' || github.ref_name }}
    env:
      SNOWFLAKE_ACCOUNT: "${{ vars.SNOWFLAKE_ACCOUNT }}"
      SNOWFLAKE_USER: "${{ vars.SNOWFLAKE_USER }}"
      SNOWFLAKE_ROLE: "${{ vars.SNOWFLAKE_ROLE }}"
      SNOWFLAKE_WAREHOUSE: "${{ vars.SNOWFLAKE_WAREHOUSE }}"
      SNOWFLAKE_DATABASE: "${{ vars.SNOWFLAKE_DATABASE }}"
      SNOWFLAKE_SCHEMA: "${{ vars.SNOWFLAKE_SCHEMA }}"
    steps:
      - name: "Checkout Repository Codebase"
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: "Set up Enterprise Python Environment"
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
          cache-dependency-path: "./requirements.txt"

      - name: "Install Core Python Dependencies"
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: "Initialize Snowflake CLI Context Interface"
        uses: snowflakedb/snowflake-cli-action@v2.0
        with:
          use-oidc: true

      - name: "Generate OIDC Token with Correct Snowflake Audience"
        uses: actions/github-script@v7
        with:
          script: |
            const token = await core.getIDToken('snowflakecomputing.com')
            core.exportVariable('SNOWFLAKE_TOKEN', token)

      # PRE-STEP: CLEAN STALE/DUPLICATE DCM DEFINITION SQL FILES
      - name: "Purge Stale DCM Definitions"
        run: |
          echo "🧹 Cleaning existing DCM definition SQL files to prevent conflicting object errors..."
          if [ -d "dcm_automation/sources/definitions" ]; then
            find dcm_automation/sources/definitions -type f -name "*.sql" -delete
          fi

      # STEP 1: RUN PYTHON ORCHESTRATION PIPELINE
      - name: "Execute Custom Python Automation Orchestrator Pipeline"
        run: |
          echo "🚀 Initializing Orchestrator Pipeline Run for Tier: [${{ github.ref_name }}]"
          SCRIPT_PATH=$(find . -name "initialise_project.py" | head -n 1)
          if [ -n "$SCRIPT_PATH" ]; then
            python "$SCRIPT_PATH" --stop-on-error
          else
            echo "❌ Fatal Error: Could not locate initialise_project.py in workspace."
            exit 1
          fi

      # STEP 2: COMMIT TO dcm_project AND AUTO-SYNC TO dev BRANCH WITH [skip ci]
      - name: "Commit & Push Generated DCM Folder to Git (dcm_project & dev)"
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          if [ -d "dcm_automation" ]; then
            git add dcm_automation/
            if ! git diff --staged --quiet; then
              git commit -m "chore(dcm): auto-generate dcm_automation definitions from orchestration [skip ci]"
              
              # Push to current branch (dcm_project)
              git push origin ${{ github.ref_name }}
              echo "✔ Successfully committed generated dcm_automation to ${{ github.ref_name }} branch!"
              
              # Sync directly to dev branch (force push to guarantee alignment)
              git push origin HEAD:refs/heads/dev --force
              echo "✔ Successfully synced generated dcm_automation to dev branch!"
            else
              echo "ℹ️ No changes in dcm_automation to commit."
            fi
          fi

      # STEP 3: UPLOAD GENERATED DCM FOLDER AS WORKFLOW ARTIFACT
      - name: "Upload DCM Artifacts"
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: dcm-automation-folder
          path: dcm_automation/

      # STEP 4: RUN DCM PLAN
      - name: "Execute DCM Plan"
        run: |
          echo "🔍 Running DCM Plan against Target: [${{ vars.DCM_TARGET }}]..."
          DCM_DIR="${{ vars.DCM_PROJECT_DIR }}"
          if [ -z "$DCM_DIR" ]; then DCM_DIR="dcm_automation"; fi
          if [ -f "$DCM_DIR/manifest.yml" ]; then
            cd "$DCM_DIR"
            snow dcm plan --target ${{ vars.DCM_TARGET }} -x
          else
            echo "DCM manifest not found ($DCM_DIR/manifest.yml), skipping plan step."
          fi

      # STEP 5: RUN DCM DEPLOY
      - name: "Execute DCM Deploy"
        run: |
          echo "🚀 Running Live DCM Deploy against Target: [${{ vars.DCM_TARGET }}]..."
          DCM_DIR="${{ vars.DCM_PROJECT_DIR }}"
          if [ -z "$DCM_DIR" ]; then DCM_DIR="dcm_automation"; fi
          if [ -f "$DCM_DIR/manifest.yml" ]; then
            cd "$DCM_DIR"
            snow dcm deploy --target ${{ vars.DCM_TARGET }} -x
          else
            echo "DCM manifest not found ($DCM_DIR/manifest.yml), skipping deploy step."
          fi
"""

def generate_dynamic_pr_gate_yml(inputs):
    """Generates a sequential transition checker tailored to custom branch sequence."""
    workflow = """# Adaptive One-way PR gate enforcement workflow
name: Enforce One-Way PR Gate
on:
  pull_request:
    types: [opened, reopened, synchronize, edited]
    branches:"""
    user_branches = [b for b in inputs['branch_sequence'] if b.lower() not in ["dcm_project", "dev"]]
    for b in user_branches:
        workflow += f"\n      - {b}"
    workflow += """

jobs:
  gate-check:
    runs-on: ubuntu-latest
    steps:"""
    all_user_branches = [b for b in inputs['branch_sequence'] if b.lower() != "dcm_project"]
    for idx in range(1, len(all_user_branches)):
        target = all_user_branches[idx]
        source = all_user_branches[idx - 1]
        workflow += f"""
      - name: Enforce {source} -> {target} gate
        if: github.event.pull_request.base.ref == '{target}' && github.event.pull_request.head.ref != '{source}'
        run: |
          echo "::error::PR routing violation. Merges into target branch '{target}' must originate from source branch '{source}'."
          exit 1"""
    workflow += """
      - name: Gate passed
        run: echo "Branch pipeline trajectory validated successfully."
"""
    return workflow

def generate_dynamic_master_delivery_yml(inputs):
    """Router linking custom branches — Passes action_type to reusable pipeline modules."""
    gh_cfg = inputs.get('github', {})
    monitored_paths = list(set(gh_cfg.get('folders_to_copy', []) + ["dcm_automation"]))
    
    paths_list = []
    for p in monitored_paths:
        p_clean = p.strip()
        if not p_clean.endswith('/**'):
            paths_list.append(f"      - '{p_clean}/**'")
        else:
            paths_list.append(f"      - '{p_clean}'")
    paths_str = "\n".join(paths_list)

    user_branches = [b for b in inputs['branch_sequence'] if b.lower() != "dcm_project"]
    branches_str = "\n".join([f"      - {b}" for b in user_branches])

    template = """name: "Standard Tier: Automated Snowflake Delivery - Master"
on:
  workflow_dispatch:
  pull_request:
    types: [opened, synchronize, reopened]
    branches:
<BRANCHES_STR>
    paths:
<PATHS_STR>
  push:
    branches:
<BRANCHES_STR>
    paths:
<PATHS_STR>

permissions:
  id-token: write 
  contents: read

jobs:"""
    workflow = template.replace("<BRANCHES_STR>", branches_str).replace("<PATHS_STR>", paths_str)
    for b in user_branches:
        workflow += f"""
  {b}-environment-plan:
    if: github.event_name == 'pull_request' && github.base_ref == '{b}'
    uses: ./.github/workflows/snowflake-pipeline-{b}.yml
    with:
      action_type: 'plan'
    secrets: inherit

  {b}-environment-deploy:
    if: github.event_name == 'push' && github.ref_name == '{b}'
    uses: ./.github/workflows/snowflake-pipeline-{b}.yml
    with:
      action_type: 'deploy'
    secrets: inherit
"""
    return workflow

def generate_dynamic_branch_pipeline_yml(b_name, b_inputs, inputs):
    """Creates standalone workflow leveraging feature flags and explicit action_type inputs."""
    sf_global = inputs.get('snowflake_global', {})
    sf_account = sf_global.get('account_identifier', '')
    sf_role = sf_global.get('admin_role', '')
    sf_warehouse = sf_global.get('warehouse', '')

    sf_user = b_inputs.get('sf_user', '')
    sf_db = b_inputs.get('sf_databases', [''])[0] if isinstance(b_inputs.get('sf_databases'), list) else ''
    sf_schema = b_inputs.get('sf_schemas', [''])[0] if isinstance(b_inputs.get('sf_schemas'), list) else ''

    setup_dcm = inputs.get('setup_dcm', True)
    dcm_dir = b_inputs.get('dcm_dir', 'dcm_automation')
    dcm_target = b_inputs.get('dcm_target', '')

    dcm_steps = ""
    if setup_dcm:
        dcm_steps = f"""
      - if: inputs.action_type == 'plan'
        name: "DCM Plan — Dry-run against {b_name.upper()} target only"
        uses: ./.github/workflows/modules/action-dcm-engine
        with:
          dcm_dir: "{dcm_dir}"
          dcm_target: "{dcm_target}"
          action_type: "plan"

      - if: inputs.action_type == 'deploy'
        name: "DCM Deploy — Apply changes to {b_name.upper()} target only"
        uses: ./.github/workflows/modules/action-dcm-engine
        with:
          dcm_dir: "{dcm_dir}"
          dcm_target: "{dcm_target}"
          action_type: "deploy"
"""

    return f"""name: "Snowflake Component: Progression Target - {b_name}"
on:
  workflow_call:
    inputs:
      action_type:
        required: true
        type: string

permissions:
  id-token: write
  contents: read

env:
  SNOWFLAKE_ACCOUNT: "{sf_account}"
  SNOWFLAKE_USER: "{sf_user}"
  SNOWFLAKE_ROLE: "{sf_role}"
  SNOWFLAKE_WAREHOUSE: "{sf_warehouse}"
  SNOWFLAKE_CLI_FEATURES_ENABLE_SNOWFLAKE_PROJECTS: "true"
  SNOWFLAKE_DATABASE: "{sf_db}"
  SNOWFLAKE_SCHEMA: "{sf_schema}"

jobs:
  {b_name}-environment-execution:
    runs-on: ubuntu-latest
    environment: {b_name} 
    steps:
      - uses: actions/checkout@v4
{dcm_steps}"""


# ==========================================================
# 🧠 PATTERN BUILDER ENGINE (Generates reference config dict)
# ==========================================================
def build_full_config_structure(
    project, owner, repo_name, user_envs, schemas, approvers,
    flags, patterns, secrets
):
    p_upper = project.strip().upper()
    p_lower = project.strip().lower()

    clean_user_envs = [e.strip().lower() for e in user_envs if e.strip() and e.strip().lower() != "dcm_project"]
    branch_sequence = clean_user_envs + ["dcm_project"]

    sf_user_pat = patterns.get("sf_user_pattern") or f"github_{p_lower}_{{env}}_user"
    cicd_db_pat = patterns.get("cicd_db_name") or f"{p_upper}_DEVOPS_DB_{{env}}"
    dcm_proj_pat = patterns.get("dcm_project") or f"{p_upper}_DCM_{{env}}"
    escape_branches = patterns.get("escape_branches", [])

    branch_data = {}
    for idx, env in enumerate(branch_sequence):
        env_upper = env.upper()
        env_lower = env.lower()
        is_first = (idx == 0)

        if env_lower == "dcm_project":
            branch_data["dcm_project"] = {
                "require_pr": False,
                "required_approvals": 0,
                "approvers": [],
                "sf_user": f"github_{p_lower}_project_user",
                "sf_roles": ["DBA_ADMIN", "DBA_FR"],
                "sf_databases": ["CICD_METADATA"],
                "sf_schemas": ["DCM_CONFIG"],
                "dcm_target": "DCM_METADATA",
                "is_default": True,
                "is_default_target": True,
                "is_default_true": True,
                "dcm_dir": "dcm_automation"
            }
        else:
            env_apps = approvers.get(env_lower, [])
            require_pr = (not is_first) and (env_lower not in escape_branches)
            req_approvals = len(env_apps) if env_apps else (1 if require_pr else 0)

            branch_data[env_lower] = {
                "require_pr": require_pr,
                "required_approvals": req_approvals,
                "approvers": env_apps,
                "sf_user": sf_user_pat.format(env=env_lower, ENV=env_upper, project=p_lower, PROJECT=p_upper),
                "sf_roles": ["DBA_ADMIN", "DBA_FR"],
                "sf_databases": [cicd_db_pat.format(env=env_upper, project=p_upper)],
                "sf_schemas": schemas,
                "dcm_target": dcm_proj_pat.format(env=env_upper, project=p_upper),
                "dcm_dir": "dcm_automation"
            }

    full_config = {
        "dcm_project_name": "dcm_automation",
        "dcm_dir": "dcm_automation",
        "snowflake_global": {
            "account_identifier": secrets.get("sf_account"),
            "admin_role": secrets.get("sf_admin_role", "PSEUDO_ACCOUNTADMIN"),
            "warehouse": secrets.get("sf_warehouse") or f"{p_upper}_DEVOPS_WH",
        },
        "roles": {
            "DBA_ADMIN": {"create": True, "read": True, "ownership": True},
            "DBA_FR": {"create": True, "read": True, "ownership": False}
        },
        "project": project,
        "project_description": "Snowflake Gated GitOps Core Offering",
        "owner": owner,
        "repo_name": repo_name,
        "branch_sequence": branch_sequence,
        "setup_repo": flags["setup_repo"],
        "setup_snowflake": flags["setup_snowflake"],
        "setup_dcm": flags["setup_dcm"],
        "escape_protection_branches": escape_branches,
        "github": {
            "repo_visibility": "public",
            "source_repository": secrets.get("source_repo", "https://github.com/kipibi/CI_CD_STANDARD_TIER_OFFERING_TEMPLATE"),
            "source_branch": secrets.get("source_branch", "dcm_template_v1"),
            "files_to_copy": ["requirements.txt", "snowflake.toml"],
            "folders_to_copy": [
                "Projects", "initialization_template",
                "helper_scripts"
            ]
        },
        "branch_data": branch_data
    }
    return full_config


# ==========================================================
# 🛠️ HELPER FUNCTIONS (REST API & SHELL EXECUTOR)
# ==========================================================
def execute_shell_cmd(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Shell execution error: {result.stderr.strip()}")
    return result.stdout

def get_github_session(token):
    session = requests.Session()
    session.headers.update({
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    })
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    return session

def create_github_environment(session, full_repo, env_name, reviewers_list, g_client):
    url = f"https://api.github.com/repos/{full_repo}/environments/{env_name}"
    reviewers = []
    for usr in reviewers_list:
        try:
            reviewers.append({"type": "User", "id": g_client.get_user(usr).id})
        except Exception:
            pass
    
    payload = {
        "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}
    }
    if reviewers:
        payload["reviewers"] = reviewers

    session.put(url, json=payload, timeout=10)

def set_github_env_var(session, full_repo, env_name, var_name, var_value):
    if isinstance(var_value, list):
        var_value = ",".join([str(v).strip() for v in var_value])
    
    check_url = f"https://api.github.com/repos/{full_repo}/environments/{env_name}/variables/{var_name}"
    payload = {"name": var_name, "value": str(var_value or "")}

    for attempt in range(3):
        try:
            resp = session.get(check_url, timeout=10)
            if resp.status_code == 200:
                session.patch(check_url, json={"value": str(var_value or "")}, timeout=10)
            else:
                create_url = f"https://api.github.com/repos/{full_repo}/environments/{env_name}/variables"
                session.post(create_url, json=payload, timeout=10)
            break
        except requests.exceptions.SSLError as ssl_err:
            if attempt == 2:
                raise ssl_err
            time.sleep(1)


# ==========================================================
# 🖥️ STREAMLIT INPUT FORM
# ==========================================================
tab1, tab2, tab3 = st.tabs([
    "1️⃣ Project & Environments", 
    "2️⃣ Feature Flags & Patterns", 
    "3️⃣ Secrets & Prerequisites"
])

# --- TAB 1: PROJECT & ENVIRONMENTS ---
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        project = st.text_input("1. Project Name *", value="pepsi", help="e.g. pepsi, cicd_demo_12")
        owner = st.text_input("2. GitHub Owner / Org *", value="GreatBat67")
        repo_name = st.text_input("3. GitHub Repo Name *", value="pepsi_cicd")
    with col2:
        raw_envs = st.text_input("4. Environments Sequence (comma-separated) *", value="dev, qa, cicd, main", help="Enter runtime branches. 'dcm_project' is appended automatically as the default target.")
        envs_list = [e.strip().lower() for e in raw_envs.split(",") if e.strip()]
        
        raw_schemas = st.text_input("5. Database Schemas (comma-separated) *", value="UTILITIES, PATIENTS, MANAGEMENT")
        schemas_list = [s.strip() for s in raw_schemas.split(",") if s.strip()]

    st.subheader("👥 Environment Approvers")
    display_envs = [e for e in envs_list if e != "dcm_project"] + ["dcm_project"]
    approvers_map = {}
    app_cols = st.columns(len(display_envs))
    for idx, env in enumerate(display_envs):
        with app_cols[idx % len(app_cols)]:
            raw_apps = st.text_input(f"Approvers [{env.upper()}]", value="GreatBat67" if env in ["qa", "cicd", "main"] else "", key=f"app_{env}")
            approvers_map[env] = [a.strip() for a in raw_apps.split(",") if a.strip()]

# --- TAB 2: FEATURE FLAGS & PATTERNS ---
with tab2:
    st.subheader("🚩 Feature Flags")
    f1, f2, f3 = st.columns(3)
    setup_repo = f1.checkbox("setup_repo", value=True)
    setup_snowflake = f2.checkbox("setup_snowflake", value=True)
    setup_dcm = f3.checkbox("setup_dcm", value=True)

    st.divider()
    st.subheader("🏷️ Naming Pattern Fallbacks (Leave empty for default)")
    p1, p2 = st.columns(2)
    with p1:
        sf_user_pattern = st.text_input("Snowflake User Pattern", value="", placeholder="NULL -> github_<project>_<env>_user")
        cicd_db_name = st.text_input("CICD Database Pattern", value="", placeholder="NULL -> PEPSI_DEVOPS_DB_<ENV>")
        escape_branches_raw = st.text_input("Escape Protection Branches", value="", placeholder="Empty = protect all branches")
        escape_branches = [b.strip().lower() for b in escape_branches_raw.split(",") if b.strip()]
    with p2:
        dcm_project = st.text_input("DCM Target Pattern", value="", placeholder="NULL -> PEPSI_DCM_<ENV>")

# --- TAB 3: SECRETS & PREREQUISITES ---
with tab3:
    st.subheader("🔒 Prerequisites & Secrets")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Snowflake Credentials**")
        sf_account = st.text_input("Snowflake Account URL/Identifier *", value="KIPI-KIPI_PRIMARY")
        sf_admin_user = st.text_input("Snowflake Admin User *", value="PSEUDO_ACCOUNTADMIN")
        sf_admin_password = st.text_input("Snowflake Password *", type="password")
        sf_admin_role = st.text_input("Admin Role Context", value="PSEUDO_ACCOUNTADMIN")
        sf_warehouse = st.text_input("Snowflake Warehouse", value="github_cicd_demo_wh")
    with c2:
        st.markdown("**GitHub Credentials**")
        github_devops_user = st.text_input("GitHub DevOps User", value="GreatBat67")
        github_pat = st.text_input("GitHub PAT *", type="password")
        source_repo = st.text_input("Source Template Repo", value="https://github.com/kipibi/CI_CD_STANDARD_TIER_OFFERING_TEMPLATE")
        source_branch = st.text_input("Source Template Branch", value="dcm_template_v1")


# ==========================================================
# EXECUTION & PROVISIONING
# ==========================================================
st.divider()
if st.button("Provision Project Infrastructure", type="primary", use_container_width=True):
    if not project.strip() or not owner.strip() or not repo_name.strip():
        st.error("Project Name, GitHub Owner, and Repo Name are required.")
        st.stop()
    if not github_pat.strip():
        st.error("GitHub PAT is required.")
        st.stop()
    if setup_snowflake and (not sf_admin_user or not sf_admin_password):
        st.error("Snowflake Admin User and Password are required when setup_snowflake is true.")
        st.stop()

    flags = {"setup_repo": setup_repo, "setup_snowflake": setup_snowflake, "setup_dcm": setup_dcm}
    patterns = {
        "sf_user_pattern": sf_user_pattern, "cicd_db_name": cicd_db_name,
        "dcm_project": dcm_project, "escape_branches": escape_branches
    }
    secrets = {
        "sf_account": sf_account, "sf_admin_role": sf_admin_role, "sf_warehouse": sf_warehouse,
        "source_repo": source_repo, "source_branch": source_branch
    }

    full_config = build_full_config_structure(
        project, owner, repo_name, envs_list, schemas_list,
        approvers_map, flags, patterns, secrets
    )

    with st.expander("🔍 View Generated System Configuration Matrix", expanded=False):
        st.json(full_config)

    status_box = st.status("Running Infrastructure Engine...", expanded=True)

    try:
        # --------------------------------------------------
        # Step 1: GitHub API Verification & Fetch Numeric IDs
        # --------------------------------------------------
        status_box.write("**Step 1/4: Connecting to GitHub & Retrieving Numeric Entity Identifiers...**")
        auth = github.Auth.Token(github_pat)
        g = Github(auth=auth)
        full_repo_path = f"{owner}/{repo_name}"

        try:
            repo_obj = g.get_repo(full_repo_path)
        except GithubException as e:
            if e.status == 404:
                authenticated_user = g.get_user()
                # Check if target owner matches authenticated user
                if authenticated_user.login.lower() == owner.lower():
                    repo_obj = authenticated_user.create_repo(name=repo_name, private=False)
                else:
                    # Attempt organization creation only if owner is a different entity
                    try:
                        org = g.get_organization(owner)
                        repo_obj = org.create_repo(name=repo_name, private=False)
                    except GithubException as org_err:
                        raise RuntimeError(
                            f"Could not find or create repository under '{owner}'. "
                            f"Verify that '{owner}' is a valid Organization or User, and that your PAT has 'repo' scope. "
                            f"Details: {org_err.data.get('message', str(org_err))}"
                        )
            else:
                raise e

        # Resolve Owner ID correctly whether User or Org
        try:
            owner_id = g.get_user(owner).id
        except GithubException:
            owner_id = g.get_organization(owner).id

        repo_id = repo_obj.id
        status_box.write(f"  ✔ Resolved GitHub Identifiers: Owner ID = [{owner_id}], Repo ID = [{repo_id}]")

        # --------------------------------------------------
        # Step 2: Snowflake Foundation Layer & OIDC Grant Setup
        # --------------------------------------------------
        if setup_snowflake:
            status_box.write("**Step 2/4: Provisioning Snowflake Foundation Layer (Warehouses, Databases, Users, OIDC Grants)...**")
            conn = snowflake.connector.connect(
                account=sf_account, user=sf_admin_user, password=sf_admin_password,
                role=sf_admin_role
            )
            cursor = conn.cursor()
            
            cursor.execute(f"CREATE WAREHOUSE IF NOT EXISTS {sf_warehouse} WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 300 AUTO_RESUME = TRUE;")

            for role_name in ["DBA_ADMIN", "DBA_FR"]:
                cursor.execute(f"CREATE ROLE IF NOT EXISTS {role_name};")
                cursor.execute(f"GRANT ROLE {role_name} TO ROLE {sf_admin_role};")

            for b_name in full_config["branch_sequence"]:
                b_profile = full_config["branch_data"][b_name]
                for db in b_profile["sf_databases"]:
                    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db};")
                    for sch in b_profile["sf_schemas"]:
                        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {db}.{sch};")

                target_user = b_profile["sf_user"]
                cursor.execute(f"CREATE USER IF NOT EXISTS {target_user} TYPE = SERVICE DEFAULT_WAREHOUSE = '{sf_warehouse}' DEFAULT_ROLE = '{sf_admin_role}';")
                cursor.execute(f"ALTER USER {target_user} SET TYPE = SERVICE;")

                # GRANT ADMIN ROLE DIRECTLY TO SERVICE USER SO SNOWPARK CAN ASSUME SNOWFLAKE_ROLE
                cursor.execute(f"GRANT ROLE {sf_admin_role} TO USER {target_user};")

                for r in b_profile["sf_roles"]:
                    cursor.execute(f"GRANT ROLE {r} TO USER {target_user};")

                # Set OIDC Workload Identity Subject with Exact Immutable GitHub Claims
                dynamic_subject = f"repo:{owner}@{owner_id}/{repo_name}@{repo_id}:environment:{b_name}"
                cursor.execute(f"ALTER USER {target_user} SET WORKLOAD_IDENTITY = (TYPE = OIDC, ISSUER = 'https://token.actions.githubusercontent.com', SUBJECT = '{dynamic_subject}');")

            cursor.close()
            conn.close()
            status_box.write("  ✔ Snowflake Foundation Layer, Service User Roles & OIDC Trust created!")

        # --------------------------------------------------
        # Step 3: GitHub Environments & Environment Variables
        # --------------------------------------------------
        if setup_repo:
            status_box.write("**Step 3/4: Populating GitHub Environment Variable Vaults...**")
            gh_session = get_github_session(github_pat)

            for b_name in full_config["branch_sequence"]:
                b_inputs = full_config["branch_data"][b_name]
                
                create_github_environment(gh_session, full_repo_path, b_name, b_inputs.get("approvers", []), g)

                primary_db = b_inputs["sf_databases"][0] if isinstance(b_inputs["sf_databases"], list) and b_inputs["sf_databases"] else b_inputs["sf_databases"]
                primary_sch = b_inputs["sf_schemas"][0] if isinstance(b_inputs["sf_schemas"], list) and b_inputs["sf_schemas"] else b_inputs["sf_schemas"]

                set_github_env_var(gh_session, full_repo_path, b_name, "SNOWFLAKE_ACCOUNT", sf_account)
                set_github_env_var(gh_session, full_repo_path, b_name, "SNOWFLAKE_ROLE", sf_admin_role)
                set_github_env_var(gh_session, full_repo_path, b_name, "SNOWFLAKE_USER", b_inputs["sf_user"])
                set_github_env_var(gh_session, full_repo_path, b_name, "SNOWFLAKE_WAREHOUSE", sf_warehouse)
                
                set_github_env_var(gh_session, full_repo_path, b_name, "SNOWFLAKE_DATABASE", primary_db)
                set_github_env_var(gh_session, full_repo_path, b_name, "SNOWFLAKE_SCHEMA", primary_sch)
                
                set_github_env_var(gh_session, full_repo_path, b_name, "SNOWFLAKE_DATABASES", b_inputs["sf_databases"])
                set_github_env_var(gh_session, full_repo_path, b_name, "SNOWFLAKE_SCHEMAS", b_inputs["sf_schemas"])
                
                set_github_env_var(gh_session, full_repo_path, b_name, "DCM_TARGET", b_inputs["dcm_target"])
                set_github_env_var(gh_session, full_repo_path, b_name, "DCM_PROJECT_DIR", b_inputs["dcm_dir"])

            status_box.write("  ✔ GitHub environments & environment variables populated!")

            # --------------------------------------------------
            # Step 4: Mirror Template Workspace & Push All Branches
            # --------------------------------------------------
            status_box.write("**Step 4/4: Mirroring Template Workspace & Pushing Branches (Native Workflow Triggers)...**")
            gh_cfg = full_config.get('github', {})
            files_to_copy = gh_cfg.get('files_to_copy', [])
            folders_to_copy = gh_cfg.get('folders_to_copy', [])

            with tempfile.TemporaryDirectory() as temp_dir:
                source_clone_dir = os.path.join(temp_dir, "src")
                target_clone_dir = os.path.join(temp_dir, "tgt")

                auth_src = source_repo.replace("https://github.com/", f"https://x-access-token:{github_pat}@github.com/")
                execute_shell_cmd(["git", "clone", "--depth", "1", "--branch", source_branch, auth_src, source_clone_dir])

                auth_tgt = f"https://x-access-token:{github_pat}@github.com/{full_repo_path}.git"
                try:
                    execute_shell_cmd(["git", "clone", auth_tgt, target_clone_dir])
                except Exception:
                    os.makedirs(target_clone_dir, exist_ok=True)
                    execute_shell_cmd(["git", "init"], cwd=target_clone_dir)
                    execute_shell_cmd(["git", "remote", "add", "origin", auth_tgt], cwd=target_clone_dir)

                    with open(os.path.join(target_clone_dir, "README.md"), "w", encoding="utf-8") as rf:
                        rf.write(f"# {repo_name}\nGitOps Framework Hierarchy.")
                    execute_shell_cmd(["git", "config", "user.name", "GitOps Bot"], cwd=target_clone_dir)
                    execute_shell_cmd(["git", "config", "user.email", "bot@gitops.internal"], cwd=target_clone_dir)
                    execute_shell_cmd(["git", "checkout", "-b", full_config['branch_sequence'][0]], cwd=target_clone_dir)
                    execute_shell_cmd(["git", "add", "README.md"], cwd=target_clone_dir)
                    execute_shell_cmd(["git", "commit", "-m", "Initial commit"], cwd=target_clone_dir)
                    execute_shell_cmd(["git", "push", "-u", "origin", full_config['branch_sequence'][0], "--force"], cwd=target_clone_dir)

                for idx, b_name in enumerate(full_config['branch_sequence']):
                    status_box.write(f"  ⚡ Synchronizing branch tier: **[{b_name.upper()}]**...")

                    try:
                        requests.delete(
                            f"https://api.github.com/repos/{full_repo_path}/branches/{b_name}/protection",
                            headers={"Authorization": f"token {github_pat}", "Accept": "application/vnd.github+json"}
                        )
                    except Exception:
                        pass

                    execute_shell_cmd(["git", "fetch", "origin"], cwd=target_clone_dir)
                    try:
                        execute_shell_cmd(["git", "checkout", b_name], cwd=target_clone_dir)
                        execute_shell_cmd(["git", "pull", "origin", b_name], cwd=target_clone_dir)
                    except Exception:
                        if idx > 0:
                            try:
                                execute_shell_cmd(["git", "checkout", full_config['branch_sequence'][idx - 1]], cwd=target_clone_dir)
                            except Exception:
                                pass
                        execute_shell_cmd(["git", "checkout", "-b", b_name], cwd=target_clone_dir)

                    # Purge files and folders
                    for tf in files_to_copy:
                        p = os.path.join(target_clone_dir, tf.strip())
                        if os.path.exists(p): os.remove(p)
                    for tf in folders_to_copy:
                        d = os.path.join(target_clone_dir, tf.strip())
                        if os.path.exists(d) and tf.strip() != ".github":
                            shutil.rmtree(d, ignore_errors=True)

                    for tf in files_to_copy:
                        src_f = os.path.join(source_clone_dir, tf.strip())
                        if os.path.exists(src_f):
                            shutil.copy2(src_f, os.path.join(target_clone_dir, tf.strip()))
                    for tf in folders_to_copy:
                        src_d = os.path.join(source_clone_dir, tf.strip())
                        if os.path.exists(src_d) and tf.strip() != ".github":
                            shutil.copytree(src_d, os.path.join(target_clone_dir, tf.strip()))

                    # PRE-CREATE dcm_automation FOLDER AND CLEAR ANY SAMPLE SQL DEFINITIONS
                    dcm_dir = os.path.join(target_clone_dir, "dcm_automation")
                    defs_dir = os.path.join(dcm_dir, "sources", "definitions")
                    
                    if os.path.exists(defs_dir):
                        for root, _, files in os.walk(defs_dir):
                            for file in files:
                                if file.endswith(".sql"):
                                    os.remove(os.path.join(root, file))

                    os.makedirs(defs_dir, exist_ok=True)
                    os.makedirs(os.path.join(dcm_dir, "sources", "macros"), exist_ok=True)
                    os.makedirs(os.path.join(dcm_dir, "out"), exist_ok=True)

                    for gk in [
                        os.path.join(dcm_dir, ".gitkeep"),
                        os.path.join(dcm_dir, "sources", "definitions", ".gitkeep"),
                        os.path.join(dcm_dir, "sources", "macros", ".gitkeep")
                    ]:
                        if not os.path.exists(gk):
                            with open(gk, "w", encoding="utf-8") as f:
                                f.write("")

                    # WRITE DYNAMIC project_config.yml DIRECTLY INTO REPO WORKSPACE
                    cfg_paths = [
                        os.path.join(target_clone_dir, "dcm_scripts_template", "config", "project_config.yml"),
                        os.path.join(target_clone_dir, "config", "project_config.yml")
                    ]
                    for cp in cfg_paths:
                        os.makedirs(os.path.dirname(cp), exist_ok=True)
                        with open(cp, "w", encoding="utf-8") as cfg_out:
                            yaml.dump(full_config, cfg_out, default_flow_style=False)

                    # PATCH config.py DIRECTLY TO GUARANTEE PROJECT_DIR IS NEVER NONE
                    config_py_path = os.path.join(target_clone_dir, "dcm_scripts_template", "config", "config.py")
                    if os.path.exists(config_py_path):
                        with open(config_py_path, "r", encoding="utf-8") as cfg_in:
                            cfg_code = cfg_in.read()
                        
                        fallback_patch = """
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
"""
                        if "GUARANTEED DIRECTORY RESOLUTION FIX" not in cfg_code:
                            cfg_code += "\n" + fallback_patch
                            with open(config_py_path, "w", encoding="utf-8") as cfg_out:
                                cfg_out.write(cfg_code)

                    # GENERATE WORKFLOW FILES
                    wf_dir = os.path.join(target_clone_dir, ".github", "workflows")
                    mod_dcm_dir = os.path.join(wf_dir, "modules", "action-dcm-engine")

                    if setup_dcm:
                        os.makedirs(mod_dcm_dir, exist_ok=True)
                        with open(os.path.join(mod_dcm_dir, "action.yml"), "w", encoding="utf-8") as out:
                            out.write(generate_dcm_action_yml())

                    os.makedirs(wf_dir, exist_ok=True)
                    with open(os.path.join(wf_dir, "pr-gate.yml"), "w", encoding="utf-8") as out:
                        out.write(generate_dynamic_pr_gate_yml(full_config))
                    with open(os.path.join(wf_dir, "snowflake-delivery-master.yml"), "w", encoding="utf-8") as out:
                        out.write(generate_dynamic_master_delivery_yml(full_config))
                    with open(os.path.join(wf_dir, "snowflake-orchestration.yml"), "w", encoding="utf-8") as out:
                        out.write(generate_manual_init_yml())

                    for env_item in full_config['branch_sequence']:
                        env_item_inputs = full_config['branch_data'][env_item]
                        with open(os.path.join(wf_dir, f"snowflake-pipeline-{env_item}.yml"), "w", encoding="utf-8") as out:
                            out.write(generate_dynamic_branch_pipeline_yml(env_item, env_item_inputs, full_config))

                    # COMMIT AND FORCE PUSH EVERY BRANCH
                    execute_shell_cmd(["git", "add", "."], cwd=target_clone_dir)
                    status = execute_shell_cmd(["git", "status", "--porcelain"], cwd=target_clone_dir)
                    if status.strip():
                        execute_shell_cmd(["git", "commit", "-m", f"Automated GitOps framework & workflow deployment for branch {b_name}"], cwd=target_clone_dir)
                    
                    execute_shell_cmd(["git", "push", "origin", b_name, "--force"], cwd=target_clone_dir)

            # APPLY BRANCH PROTECTION RULES ACCORDING TO STRICT GITOPS GOVERNANCE
            for b_name in full_config['branch_sequence']:
                b_inputs = full_config['branch_data'][b_name]
                require_pr = b_inputs.get("require_pr", False)

                # EXPLICITLY REMOVE/SKIP PROTECTION FOR UNPROTECTED BRANCHES (dev, dcm_project, AND ESCAPE BRANCHES)
                if not require_pr or b_name.lower() in escape_branches or b_name.lower() in ["dcm_project", "dev"]:
                    status_box.write(f"  ℹ️ Ensuring branch remains unlocked for direct updates: [{b_name}]")
                    try:
                        gh_session.delete(
                            f"https://api.github.com/repos/{full_repo_path}/branches/{b_name}/protection",
                            timeout=10
                        )
                    except Exception:
                        pass
                    continue

                # LOCK HIGHER ENVIRONMENT BRANCHES (qa, cicd, main, etc.)
                try:
                    req_approvals = b_inputs.get("required_approvals", 1)

                    prot_url = f"https://api.github.com/repos/{full_repo_path}/branches/{b_name}/protection"
                    prot_payload = {
                        "required_status_checks": None,
                        "enforce_admins": True,
                        "required_pull_request_reviews": {
                            "dismiss_stale_reviews": True,
                            "require_code_owner_reviews": False,
                            "required_approving_review_count": req_approvals
                        },
                        "restrictions": None
                    }
                    gh_session.put(prot_url, json=prot_payload, timeout=10)
                    status_box.write(f"  🔒 Protected branch **[{b_name}]** (Required Approvals: {req_approvals})")
                except Exception as prot_err:
                    status_box.write(f"  ⚠️ Warning setting protection on [{b_name}]: {str(prot_err)}")

            status_box.write("  ✔ All branches, project configuration, and workflows initialized successfully!")
            status_box.update(label="🎉 GitOps Infrastructure Provisioning Complete!", state="complete", expanded=False)
            st.success(f"Successfully provisioned **{owner}/{repo_name}**!")
            st.markdown(f"🔗 **GitHub Repo:** [https://github.com/{owner}/{repo_name}](https://github.com/{owner}/{repo_name})")

    except Exception as err:
        status_box.update(label="❌ Provisioning Failed", state="error")
        st.error(f"Execution Error: {str(err)}")
