#!/usr/bin/env bash
# setup-skill-ubuntu.sh
#
# Alternative to setup-ubuntu.sh that installs copilot-ado-skills as a
# GitHub Copilot CLI *built-in skill* instead of an MCP server.
#
# Use this script when the MCP server feature is unavailable or disabled in
# your Copilot CLI installation.  The skill uses a simple one-shot invocation
# model: for every function call Copilot CLI spawns the skill binary, passes
# the JSON parameters on stdin, and reads the JSON result from stdout.  No
# long-running server process is required.
#
# What this script does
# ---------------------
#   1. Verifies / installs Python 3.10+ and pip (via apt when needed).
#   2. Verifies / installs Node.js 22.x and npm (needed for Copilot CLI).
#   3. Verifies / installs GitHub Copilot CLI (@github/copilot npm package).
#   4. Creates a Python virtual environment in .venv and runs pip install -e .
#      so that `copilot-ado-skills-invoke` is available inside the venv.
#   5. Writes a skill YAML manifest to ~/.copilot/skills/ado-git.yaml
#      (or $COPILOT_HOME/skills/ado-git.yaml).
#
# Usage
# -----
#   chmod +x ./scripts/setup-skill-ubuntu.sh
#   ./scripts/setup-skill-ubuntu.sh --org-url "https://dev.azure.com/<your-org>"
#
#   # Persist a PAT inside the skill env block:
#   export AZURE_DEVOPS_PAT="<your-pat>"
#   ./scripts/setup-skill-ubuntu.sh \
#       --org-url "https://dev.azure.com/<your-org>" \
#       --write-pat

set -euo pipefail

MIN_NODE_MAJOR=22
SKILL_NAME="${SKILL_NAME:-ado-git}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
COPILOT_HOME_DIR="${COPILOT_HOME:-${HOME}/.copilot}"
SKILLS_DIR="${COPILOT_HOME_DIR}/skills"
SKILL_DIR="${SKILLS_DIR}/${SKILL_NAME}"
SKILL_MANIFEST_PATH="${SKILL_DIR}/SKILL.md"
ORG_URL="${AZURE_DEVOPS_ORG_URL:-}"
WRITE_PAT_TO_SKILL_MANIFEST=false

APT_UPDATED=false

log() {
  printf '[setup-skill] %s\n' "$*"
}

warn() {
  printf '[setup-skill] warning: %s\n' "$*" >&2
}

die() {
  printf '[setup-skill] error: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [--org-url URL] [--skill-name NAME] [--write-pat]

Installs or verifies Python, pip, Node.js, npm, GitHub Copilot CLI, and the
local copilot-ado-skills built-in skill on Ubuntu/Debian systems.

This is an alternative to setup-ubuntu.sh for environments where the Copilot
CLI MCP server feature is unavailable or disabled.  The skill is installed as
a one-shot command invoked by Copilot CLI via ~/.copilot/skills/<name>.yaml.

Options:
  --org-url URL      Azure DevOps organization URL to store in the skill manifest
  --skill-name NAME  Skill name written to the manifest file (default: ado-git)
  --write-pat        Persist AZURE_DEVOPS_PAT into the skill manifest env block
  --help             Show this help text

Environment:
  AZURE_DEVOPS_ORG_URL  Default value for --org-url
  AZURE_DEVOPS_PAT      Optional PAT; only written when --write-pat is used
  COPILOT_HOME          Overrides the Copilot config directory (default: ~/.copilot)
  SKILL_NAME            Default value for --skill-name
EOF
}

run_with_sudo() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    die "sudo is required to install system packages"
  fi
}

apt_update_once() {
  if [[ "${APT_UPDATED}" == "false" ]]; then
    log "Updating apt package lists"
    run_with_sudo apt-get update
    APT_UPDATED=true
  fi
}

apt_install() {
  apt_update_once
  run_with_sudo apt-get install -y "$@"
}

python3_is_supported() {
  command -v python3 >/dev/null 2>&1 || return 1
  python3 - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

node_is_supported() {
  command -v node >/dev/null 2>&1 || return 1
  local major
  major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)"
  [[ -n "${major}" && "${major}" -ge "${MIN_NODE_MAJOR}" ]]
}

print_version() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    log "${label}: $("$@" 2>/dev/null | head -n 1)"
  else
    log "${label}: not installed"
  fi
}

ensure_python_toolchain() {
  if python3_is_supported \
    && python3 -m pip --version >/dev/null 2>&1 \
    && python3 -m venv --help >/dev/null 2>&1; then
    return
  fi

  log "Installing Python tooling"
  apt_install python3 python3-pip python3-venv

  if ! python3_is_supported; then
    die "python3 >= 3.10 is required; use Ubuntu 22.04+ or install a newer Python manually"
  fi

  python3 -m pip --version >/dev/null 2>&1 || die "python3-pip could not be installed"

  if python3 -m venv --help >/dev/null 2>&1; then
    return
  fi

  local python_version versioned_venv_package
  python_version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  versioned_venv_package="python${python_version}-venv"

  log "Installing ${versioned_venv_package} for the active python3 interpreter"
  apt_install "${versioned_venv_package}"

  python3 -m venv --help >/dev/null 2>&1 \
    || die "python venv support is still unavailable after installing ${versioned_venv_package}"
}

install_nodesource_repo() {
  apt_install ca-certificates curl gnupg
  run_with_sudo mkdir -p /etc/apt/keyrings

  if [[ ! -f /etc/apt/keyrings/nodesource.gpg ]]; then
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | run_with_sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
  fi

  if [[ ! -f /etc/apt/sources.list.d/nodesource.list ]] \
    || ! grep -q "node_${MIN_NODE_MAJOR}\.x" /etc/apt/sources.list.d/nodesource.list 2>/dev/null; then
    printf 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_%s.x nodistro main\n' "${MIN_NODE_MAJOR}" \
      | run_with_sudo tee /etc/apt/sources.list.d/nodesource.list >/dev/null
  fi

  APT_UPDATED=false
}

ensure_node_toolchain() {
  if node_is_supported && command -v npm >/dev/null 2>&1; then
    return
  fi

  log "Installing Node.js ${MIN_NODE_MAJOR}.x and npm"
  install_nodesource_repo
  apt_install nodejs

  node_is_supported || die "node >= ${MIN_NODE_MAJOR} is required after installation"
  command -v npm >/dev/null 2>&1 || die "npm was not installed with nodejs"
}

install_copilot_cli() {
  if command -v copilot >/dev/null 2>&1; then
    log "GitHub Copilot CLI already installed: $(copilot --version 2>/dev/null | head -n 1)"
    return
  fi

  log "Installing GitHub Copilot CLI"
  if [[ "$(npm config get ignore-scripts 2>/dev/null || true)" == "true" ]]; then
    if [[ -w "$(npm prefix -g)" ]]; then
      npm_config_ignore_scripts=false npm install -g @github/copilot
    else
      run_with_sudo env npm_config_ignore_scripts=false npm install -g @github/copilot
    fi
  else
    if [[ -w "$(npm prefix -g)" ]]; then
      npm install -g @github/copilot
    else
      run_with_sudo npm install -g @github/copilot
    fi
  fi

  command -v copilot >/dev/null 2>&1 || die "copilot CLI installation completed but 'copilot' is not on PATH"
  log "Installed GitHub Copilot CLI: $(copilot --version 2>/dev/null | head -n 1)"
}

ensure_org_url() {
  if [[ -n "${ORG_URL}" ]]; then
    return
  fi

  if [[ -t 0 ]]; then
    read -r -p "Azure DevOps organization URL (for example https://dev.azure.com/your-org): " ORG_URL
  fi

  [[ -n "${ORG_URL}" ]] || die "AZURE_DEVOPS_ORG_URL is required"
}

install_local_skill() {
  log "Creating or updating the local virtual environment"
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/pip" install -e "${REPO_ROOT}"

  # Verify the invoke entry point was installed
  [[ -x "${VENV_DIR}/bin/copilot-ado-skills-invoke" ]] \
    || die "copilot-ado-skills-invoke was not installed into the virtual environment"
}

write_skill_manifest() {
  log "Writing Copilot skill SKILL.md to ${SKILL_MANIFEST_PATH}"

  local persisted_pat=""
  if [[ "${WRITE_PAT_TO_SKILL_MANIFEST}" == "true" ]]; then
    persisted_pat="${AZURE_DEVOPS_PAT:-}"
    [[ -n "${persisted_pat}" ]] || die "--write-pat was provided but AZURE_DEVOPS_PAT is empty"
  elif [[ -n "${AZURE_DEVOPS_PAT:-}" ]]; then
    warn "AZURE_DEVOPS_PAT is set but will not be stored; rerun with --write-pat to persist it"
  fi

  SKILL_MANIFEST_PATH="${SKILL_MANIFEST_PATH}" \
  SKILL_NAME="${SKILL_NAME}" \
  INVOKE_COMMAND="${VENV_DIR}/bin/copilot-ado-skills-invoke" \
  ORG_URL="${ORG_URL}" \
  AZURE_DEVOPS_PAT="${persisted_pat}" \
  python3 - <<'PY'
import os
from pathlib import Path

skill_md_path = Path(os.environ["SKILL_MANIFEST_PATH"])
skill_md_path.parent.mkdir(parents=True, exist_ok=True)

skill_name   = os.environ["SKILL_NAME"]
invoke_cmd   = os.environ["INVOKE_COMMAND"]
org_url      = os.environ["ORG_URL"]
pat          = os.environ.get("AZURE_DEVOPS_PAT", "")

# Build the env-prefix used in every example invocation.
# If a PAT was stored we embed both env vars; otherwise just the org URL.
if pat:
    env_prefix = f'AZURE_DEVOPS_ORG_URL="{org_url}" AZURE_DEVOPS_PAT="{pat}" '
else:
    env_prefix = f'AZURE_DEVOPS_ORG_URL="{org_url}" '

skill_md = f"""\
---
name: {skill_name}
description: >-
  Azure DevOps Git skill. Provides git operations, pull-request management,
  and repository/code search against Azure DevOps organizations.
user-invocable: true
---

# Azure DevOps Git Skill

This skill lets you interact with Azure DevOps git repositories, pull requests,
and code search through the `copilot-ado-skills-invoke` one-shot CLI.

## Invoking functions

Each function is called by piping a JSON object to the invoke binary:

```bash
printf '%s' '<json_params>' | {env_prefix}{invoke_cmd} <function_name>
```

The binary writes a JSON result to stdout.  Use an empty object (`{{}}`) when a
function requires no parameters beyond the environment variables.

## Git operations

### clone_repository
Clone an ADO repository to a local directory.
Required: `remote_url` (string), `destination` (string).
Optional: `branch` (string).
```bash
printf '%s' '{{"remote_url":"<url>","destination":"<path>"}}' | {env_prefix}{invoke_cmd} clone_repository
```

### checkout_branch
Check out a branch (optionally creating it).
Required: `working_dir`, `branch`.  Optional: `create` (bool, default false).
```bash
printf '%s' '{{"working_dir":"<path>","branch":"<name>"}}' | {env_prefix}{invoke_cmd} checkout_branch
```

### create_branch
Create a new local branch.
Required: `working_dir`, `branch`.  Optional: `base_branch`.
```bash
printf '%s' '{{"working_dir":"<path>","branch":"<name>"}}' | {env_prefix}{invoke_cmd} create_branch
```

### commit_changes
Stage and commit local changes.
Required: `working_dir`, `message`.  Optional: `add_all` (bool, default true).
```bash
printf '%s' '{{"working_dir":"<path>","message":"<msg>"}}' | {env_prefix}{invoke_cmd} commit_changes
```

### push_changes
Push commits to the ADO remote.
Required: `working_dir`.  Optional: `remote` (default `origin`), `branch`, `set_upstream` (bool, default true).
```bash
printf '%s' '{{"working_dir":"<path>"}}' | {env_prefix}{invoke_cmd} push_changes
```

### pull_changes
Pull the latest changes from the ADO remote.
Required: `working_dir`.  Optional: `remote`, `branch`.
```bash
printf '%s' '{{"working_dir":"<path>"}}' | {env_prefix}{invoke_cmd} pull_changes
```

### get_status
Return branch, modified, staged, and untracked files.
Required: `working_dir`.
```bash
printf '%s' '{{"working_dir":"<path>"}}' | {env_prefix}{invoke_cmd} get_status
```

### get_diff
Return a unified diff.
Required: `working_dir`.  Optional: `base` (default `HEAD`), `target`, `file_path`.
```bash
printf '%s' '{{"working_dir":"<path>"}}' | {env_prefix}{invoke_cmd} get_diff
```

### list_branches
List local and remote branches.
Required: `working_dir`.
```bash
printf '%s' '{{"working_dir":"<path>"}}' | {env_prefix}{invoke_cmd} list_branches
```

### get_log
Return recent commit history.
Required: `working_dir`.  Optional: `max_count` (int, default 20), `branch`.
```bash
printf '%s' '{{"working_dir":"<path>"}}' | {env_prefix}{invoke_cmd} get_log
```

## Pull requests

### create_pull_request
Create a PR in Azure DevOps (target branch defaults to `main`).
Required: `project`, `repository`, `title`, `source_branch`.
Optional: `target_branch`, `description`, `auto_complete` (bool), `draft` (bool), `organization_url`.
```bash
printf '%s' '{{"project":"<proj>","repository":"<repo>","title":"<t>","source_branch":"<b>"}}' | {env_prefix}{invoke_cmd} create_pull_request
```

### list_pull_requests
List PRs in a repository.
Required: `project`, `repository`.  Optional: `status` (active|completed|abandoned|all), `top`, `organization_url`.
```bash
printf '%s' '{{"project":"<proj>","repository":"<repo>"}}' | {env_prefix}{invoke_cmd} list_pull_requests
```

### get_pull_request
Get details of a specific PR.
Required: `project`, `repository`, `pull_request_id` (int).  Optional: `organization_url`.
```bash
printf '%s' '{{"project":"<proj>","repository":"<repo>","pull_request_id":42}}' | {env_prefix}{invoke_cmd} get_pull_request
```

### get_pr_comments
Get all comment threads on a PR, including inline file/line context.
Required: `project`, `repository`, `pull_request_id` (int).  Optional: `organization_url`.
```bash
printf '%s' '{{"project":"<proj>","repository":"<repo>","pull_request_id":42}}' | {env_prefix}{invoke_cmd} get_pr_comments
```

### reply_to_pr_comment
Post a reply to an existing PR comment thread.
Required: `project`, `repository`, `pull_request_id` (int), `thread_id` (int), `content`.
Optional: `organization_url`.
```bash
printf '%s' '{{"project":"<proj>","repository":"<repo>","pull_request_id":42,"thread_id":1,"content":"<text>"}}' | {env_prefix}{invoke_cmd} reply_to_pr_comment
```

### apply_pr_suggestion
Apply an inline PR suggestion to the local working tree and commit it.
Required: `working_dir`, `file_path`, `start_line` (int), `end_line` (int), `suggested_content`.
Optional: `commit_message`.
```bash
printf '%s' '{{"working_dir":"<path>","file_path":"src/x.py","start_line":5,"end_line":7,"suggested_content":"<code>"}}' | {env_prefix}{invoke_cmd} apply_pr_suggestion
```

## Repository and code search

### list_repositories
List all git repositories in an ADO project.
Required: `project`.  Optional: `organization_url`.
```bash
printf '%s' '{{"project":"<proj>"}}' | {env_prefix}{invoke_cmd} list_repositories
```

### search_repositories
Case-insensitive name search for repositories.
Required: `project`, `query`.  Optional: `organization_url`.
```bash
printf '%s' '{{"project":"<proj>","query":"<term>"}}' | {env_prefix}{invoke_cmd} search_repositories
```

### get_repository
Get details of a specific repository.
Required: `project`, `repository`.  Optional: `organization_url`.
```bash
printf '%s' '{{"project":"<proj>","repository":"<repo>"}}' | {env_prefix}{invoke_cmd} get_repository
```

### search_code
Search source code across ADO repositories (supports `ext:py`, `file:main.py`, `repo:my-repo`).
Required: `project`, `query`.  Optional: `repository`, `top` (default 25), `organization_url`.
```bash
printf '%s' '{{"project":"<proj>","query":"<query>"}}' | {env_prefix}{invoke_cmd} search_code
```

### get_file_content
Retrieve raw file content from an ADO repository without cloning.
Required: `project`, `repository`, `file_path`.  Optional: `branch` (default `main`), `organization_url`.
```bash
printf '%s' '{{"project":"<proj>","repository":"<repo>","file_path":"README.md"}}' | {env_prefix}{invoke_cmd} get_file_content
```

### list_repository_items
List files and directories in a repository path.
Required: `project`, `repository`.  Optional: `path` (default `/`), `branch`, `recursive` (bool), `organization_url`.
```bash
printf '%s' '{{"project":"<proj>","repository":"<repo>"}}' | {env_prefix}{invoke_cmd} list_repository_items
```
"""

skill_md_path.write_text(skill_md)
print(f"[setup-skill] SKILL.md written to {skill_md_path}", flush=True)
PY
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --org-url)
        [[ $# -ge 2 ]] || die "--org-url requires a value"
        ORG_URL="$2"
        shift 2
        ;;
      --skill-name)
        [[ $# -ge 2 ]] || die "--skill-name requires a value"
        SKILL_NAME="$2"
        SKILL_DIR="${SKILLS_DIR}/${SKILL_NAME}"
        SKILL_MANIFEST_PATH="${SKILL_DIR}/SKILL.md"
        shift 2
        ;;
      --write-pat)
        WRITE_PAT_TO_SKILL_MANIFEST=true
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done
}

main() {
  parse_args "$@"

  print_version "python3" python3 --version
  print_version "pip" python3 -m pip --version
  print_version "node" node --version
  print_version "npm" npm --version

  ensure_python_toolchain
  ensure_node_toolchain
  install_copilot_cli
  ensure_org_url
  install_local_skill
  write_skill_manifest

  log "Setup complete"
  log "Skill SKILL.md: ${SKILL_MANIFEST_PATH}"
  log "Invoke binary:  ${VENV_DIR}/bin/copilot-ado-skills-invoke"
  log ""
  log "Start 'copilot' and type '/${SKILL_NAME}' or ask:"
  log "  List the Azure DevOps repositories in project MyProject using the ${SKILL_NAME} skill."
}

main "$@"
