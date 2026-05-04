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
SKILL_MANIFEST_PATH="${SKILLS_DIR}/${SKILL_NAME}.yaml"
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
  log "Writing Copilot skill manifest to ${SKILL_MANIFEST_PATH}"

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
import sys
from pathlib import Path

manifest_path = Path(os.environ["SKILL_MANIFEST_PATH"])
manifest_path.parent.mkdir(parents=True, exist_ok=True)

skill_name   = os.environ["SKILL_NAME"]
invoke_cmd   = os.environ["INVOKE_COMMAND"]
org_url      = os.environ["ORG_URL"]
pat          = os.environ.get("AZURE_DEVOPS_PAT", "")

# Build the env block for the skill invocation
env_lines = [f'      AZURE_DEVOPS_ORG_URL: "{org_url}"']
if pat:
    env_lines.append(f'      AZURE_DEVOPS_PAT: "{pat}"')
env_block = "\n".join(env_lines)

# Each function shares the same invocation template; Copilot CLI passes the
# function name as the first argument and sends the JSON parameters on stdin.
manifest = f"""\
# GitHub Copilot CLI built-in skill manifest — generated by setup-skill-ubuntu.sh
#
# This file registers all Azure DevOps Git tools as a local Copilot skill.
# Copilot CLI invokes `copilot-ado-skills-invoke <function_name>` for each
# tool call.  Parameters are passed as a JSON object on stdin; the result is
# returned as a JSON object on stdout.
#
# To regenerate this file, re-run scripts/setup-skill-ubuntu.sh.

schema_version: v1
name: {skill_name}
description: >-
  Azure DevOps Git skill. Provides git operations, pull-request management,
  and repository/code search against Azure DevOps organisations.

# Environment variables injected into every invocation of this skill.
# These values are written at install time by setup-skill-ubuntu.sh.
env:
{env_block}

# ── Tool definitions ──────────────────────────────────────────────────────────
# Each entry maps to a function exposed by copilot-ado-skills-invoke.
# The `command` key lists the full argv; Copilot CLI pipes JSON parameters to
# stdin and reads the JSON result from stdout.

functions:

  # ── Git operations ──────────────────────────────────────────────────────────

  - name: clone_repository
    description: >-
      Clone an Azure DevOps git repository to a local directory.
      Returns the local path and active branch.
    parameters:
      type: object
      properties:
        remote_url:
          type: string
          description: HTTPS or SSH URL of the remote ADO repository.
        destination:
          type: string
          description: Local filesystem path to clone into.
        branch:
          type: string
          description: Branch to check out after cloning (optional).
      required: [remote_url, destination]
    command: ["{invoke_cmd}", "clone_repository"]

  - name: checkout_branch
    description: >-
      Check out a branch in an existing local git repository.
      Optionally create the branch if it does not exist.
    parameters:
      type: object
      properties:
        working_dir:
          type: string
          description: Local repo path.
        branch:
          type: string
          description: Branch to check out.
        create:
          type: boolean
          description: Create branch if it does not exist.
          default: false
      required: [working_dir, branch]
    command: ["{invoke_cmd}", "checkout_branch"]

  - name: create_branch
    description: Create a new git branch in a local repository.
    parameters:
      type: object
      properties:
        working_dir:
          type: string
        branch:
          type: string
          description: Name for the new branch.
        base_branch:
          type: string
          description: Branch to base the new branch on (defaults to HEAD).
      required: [working_dir, branch]
    command: ["{invoke_cmd}", "create_branch"]

  - name: commit_changes
    description: Stage and commit local changes in a git repository.
    parameters:
      type: object
      properties:
        working_dir:
          type: string
        message:
          type: string
          description: Commit message.
        add_all:
          type: boolean
          description: Stage all changes before committing.
          default: true
      required: [working_dir, message]
    command: ["{invoke_cmd}", "commit_changes"]

  - name: push_changes
    description: Push committed changes to the Azure DevOps remote repository.
    parameters:
      type: object
      properties:
        working_dir:
          type: string
        remote:
          type: string
          default: origin
        branch:
          type: string
          description: Branch to push (defaults to current branch).
        set_upstream:
          type: boolean
          default: true
          description: Set the upstream tracking branch.
      required: [working_dir]
    command: ["{invoke_cmd}", "push_changes"]

  - name: pull_changes
    description: Pull the latest changes from the Azure DevOps remote repository.
    parameters:
      type: object
      properties:
        working_dir:
          type: string
        remote:
          type: string
          default: origin
        branch:
          type: string
          description: Remote branch to pull (defaults to current).
      required: [working_dir]
    command: ["{invoke_cmd}", "pull_changes"]

  - name: get_status
    description: >-
      Return the working-tree status of a local git repository:
      current branch, modified, staged, and untracked files.
    parameters:
      type: object
      properties:
        working_dir:
          type: string
      required: [working_dir]
    command: ["{invoke_cmd}", "get_status"]

  - name: get_diff
    description: Return a unified diff of changes in a local git repository.
    parameters:
      type: object
      properties:
        working_dir:
          type: string
        base:
          type: string
          default: HEAD
          description: Base ref to diff from.
        target:
          type: string
          description: Target ref (omit to diff against working tree).
        file_path:
          type: string
          description: Restrict diff to this file (optional).
      required: [working_dir]
    command: ["{invoke_cmd}", "get_diff"]

  - name: list_branches
    description: List local and remote branches in a git repository.
    parameters:
      type: object
      properties:
        working_dir:
          type: string
      required: [working_dir]
    command: ["{invoke_cmd}", "list_branches"]

  - name: get_log
    description: Return the recent commit log of a git repository.
    parameters:
      type: object
      properties:
        working_dir:
          type: string
        max_count:
          type: integer
          default: 20
        branch:
          type: string
      required: [working_dir]
    command: ["{invoke_cmd}", "get_log"]

  # ── Pull requests ────────────────────────────────────────────────────────────

  - name: create_pull_request
    description: >-
      Create a pull request in Azure DevOps.
      Defaults to targeting the 'main' branch.
    parameters:
      type: object
      properties:
        project:
          type: string
          description: ADO project name or ID.
        repository:
          type: string
          description: Repository name or ID.
        title:
          type: string
        description:
          type: string
          default: ""
        source_branch:
          type: string
          description: Source branch (must already exist on remote).
        target_branch:
          type: string
          default: main
          description: Target branch (default: main).
        organization_url:
          type: string
        auto_complete:
          type: boolean
          default: false
        draft:
          type: boolean
          default: false
      required: [project, repository, title, source_branch]
    command: ["{invoke_cmd}", "create_pull_request"]

  - name: list_pull_requests
    description: List pull requests in an Azure DevOps repository.
    parameters:
      type: object
      properties:
        project:
          type: string
        repository:
          type: string
        status:
          type: string
          enum: [active, completed, abandoned, all]
          default: active
        organization_url:
          type: string
        top:
          type: integer
          default: 50
      required: [project, repository]
    command: ["{invoke_cmd}", "list_pull_requests"]

  - name: get_pull_request
    description: Get details of a specific pull request.
    parameters:
      type: object
      properties:
        project:
          type: string
        repository:
          type: string
        pull_request_id:
          type: integer
        organization_url:
          type: string
      required: [project, repository, pull_request_id]
    command: ["{invoke_cmd}", "get_pull_request"]

  - name: get_pr_comments
    description: >-
      Retrieve all comment threads on a pull request, including
      inline (file-level) threads with line context.
    parameters:
      type: object
      properties:
        project:
          type: string
        repository:
          type: string
        pull_request_id:
          type: integer
        organization_url:
          type: string
      required: [project, repository, pull_request_id]
    command: ["{invoke_cmd}", "get_pr_comments"]

  - name: reply_to_pr_comment
    description: Post a reply to an existing pull request comment thread.
    parameters:
      type: object
      properties:
        project:
          type: string
        repository:
          type: string
        pull_request_id:
          type: integer
        thread_id:
          type: integer
        content:
          type: string
        organization_url:
          type: string
      required: [project, repository, pull_request_id, thread_id, content]
    command: ["{invoke_cmd}", "reply_to_pr_comment"]

  - name: apply_pr_suggestion
    description: >-
      Apply an inline code suggestion from a PR review to the local
      working tree and commit it.  Replaces lines start_line–end_line
      (1-based, inclusive) in file_path with suggested_content.
    parameters:
      type: object
      properties:
        working_dir:
          type: string
        file_path:
          type: string
          description: Repo-relative path of the file to modify.
        start_line:
          type: integer
        end_line:
          type: integer
        suggested_content:
          type: string
        commit_message:
          type: string
          default: Apply inline PR suggestion
      required: [working_dir, file_path, start_line, end_line, suggested_content]
    command: ["{invoke_cmd}", "apply_pr_suggestion"]

  # ── Repository & code search ─────────────────────────────────────────────────

  - name: list_repositories
    description: List all git repositories in an Azure DevOps project.
    parameters:
      type: object
      properties:
        project:
          type: string
        organization_url:
          type: string
      required: [project]
    command: ["{invoke_cmd}", "list_repositories"]

  - name: search_repositories
    description: >-
      Search for repositories by name within an Azure DevOps project
      (case-insensitive substring match).
    parameters:
      type: object
      properties:
        project:
          type: string
        query:
          type: string
        organization_url:
          type: string
      required: [project, query]
    command: ["{invoke_cmd}", "search_repositories"]

  - name: get_repository
    description: Get details of a specific Azure DevOps repository.
    parameters:
      type: object
      properties:
        project:
          type: string
        repository:
          type: string
        organization_url:
          type: string
      required: [project, repository]
    command: ["{invoke_cmd}", "get_repository"]

  - name: search_code
    description: >-
      Search source code across Azure DevOps repositories using the
      ADO Search API.  Useful for understanding existing implementations
      before making changes.  Supports ADO search operators:
      ext:py, file:main.py, repo:my-repo.
    parameters:
      type: object
      properties:
        project:
          type: string
        query:
          type: string
          description: Search query (ADO code search syntax).
        organization_url:
          type: string
        repository:
          type: string
          description: Restrict search to this repository (optional).
        top:
          type: integer
          default: 25
      required: [project, query]
    command: ["{invoke_cmd}", "search_code"]

  - name: get_file_content
    description: >-
      Retrieve the raw content of a file from an Azure DevOps
      repository without cloning it locally.
    parameters:
      type: object
      properties:
        project:
          type: string
        repository:
          type: string
        file_path:
          type: string
        branch:
          type: string
          default: main
        organization_url:
          type: string
      required: [project, repository, file_path]
    command: ["{invoke_cmd}", "get_file_content"]

  - name: list_repository_items
    description: List files and directories in a repository path.
    parameters:
      type: object
      properties:
        project:
          type: string
        repository:
          type: string
        path:
          type: string
          default: /
        branch:
          type: string
          default: main
        recursive:
          type: boolean
          default: false
        organization_url:
          type: string
      required: [project, repository]
    command: ["{invoke_cmd}", "list_repository_items"]
"""

manifest_path.write_text(manifest)
print(f"[setup-skill] Skill manifest written to {manifest_path}", flush=True)
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
        SKILL_MANIFEST_PATH="${SKILLS_DIR}/${SKILL_NAME}.yaml"
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
  log "Skill manifest: ${SKILL_MANIFEST_PATH}"
  log "Invoke binary:  ${VENV_DIR}/bin/copilot-ado-skills-invoke"
  log ""
  log "Start 'copilot' and ask a question such as:"
  log "  List the Azure DevOps repositories in project MyProject using the ${SKILL_NAME} skill."
}

main "$@"
