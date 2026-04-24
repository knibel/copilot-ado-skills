#!/usr/bin/env bash

set -euo pipefail

MIN_NODE_MAJOR=22
SERVER_NAME="${SERVER_NAME:-ado-git}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
COPILOT_HOME_DIR="${COPILOT_HOME:-${HOME}/.copilot}"
MCP_CONFIG_PATH="${COPILOT_HOME_DIR}/mcp-config.json"
ORG_URL="${AZURE_DEVOPS_ORG_URL:-}"
WRITE_PAT_TO_MCP_CONFIG=false

APT_UPDATED=false

log() {
  printf '[setup] %s\n' "$*"
}

warn() {
  printf '[setup] warning: %s\n' "$*" >&2
}

die() {
  printf '[setup] error: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [--org-url URL] [--server-name NAME] [--write-pat]

Installs or verifies Python, pip, Node.js, npm, GitHub Copilot CLI, and the
local copilot-ado-skills MCP server on Ubuntu/Debian systems.

Options:
  --org-url URL      Azure DevOps organization URL to store in MCP config
  --server-name NAME MCP server name to write to mcp-config.json (default: ado-git)
  --write-pat        Persist AZURE_DEVOPS_PAT into the Copilot MCP config file
  --help             Show this help text

Environment:
  AZURE_DEVOPS_ORG_URL  Default value for --org-url
  AZURE_DEVOPS_PAT      Optional PAT; only written when --write-pat is used
  COPILOT_HOME          Overrides the Copilot config directory (default: ~/.copilot)
  SERVER_NAME           Default value for --server-name
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
  python_version="$(python3 - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
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

install_local_server() {
  log "Creating or updating the local virtual environment"
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/pip" install -e "${REPO_ROOT}"
}

write_mcp_config() {
  log "Writing Copilot MCP configuration to ${MCP_CONFIG_PATH}"

  local persisted_pat=""
  if [[ "${WRITE_PAT_TO_MCP_CONFIG}" == "true" ]]; then
    persisted_pat="${AZURE_DEVOPS_PAT:-}"
    [[ -n "${persisted_pat}" ]] || die "--write-pat was provided but AZURE_DEVOPS_PAT is empty"
  elif [[ -n "${AZURE_DEVOPS_PAT:-}" ]]; then
    warn "AZURE_DEVOPS_PAT is set but will not be stored; rerun with --write-pat to persist it"
  fi

  MCP_CONFIG_PATH="${MCP_CONFIG_PATH}" \
  SERVER_NAME="${SERVER_NAME}" \
  SERVER_COMMAND="${VENV_DIR}/bin/copilot-ado-skills" \
  ORG_URL="${ORG_URL}" \
  AZURE_DEVOPS_PAT="${persisted_pat}" \
  python3 - <<'PY'
import json
import os
import sys
from pathlib import Path

config_path = Path(os.environ["MCP_CONFIG_PATH"])
config_path.parent.mkdir(parents=True, exist_ok=True)

if config_path.exists():
    try:
        config = json.loads(config_path.read_text())
    except json.JSONDecodeError as exc:
        sys.exit(f"Existing MCP config is not valid JSON: {exc}")
else:
    config = {}

servers = config.setdefault("mcpServers", {})
if not isinstance(servers, dict):
    sys.exit("Existing MCP config has a non-object 'mcpServers' value")

server_env = {"AZURE_DEVOPS_ORG_URL": os.environ["ORG_URL"]}
if os.environ.get("AZURE_DEVOPS_PAT"):
    server_env["AZURE_DEVOPS_PAT"] = os.environ["AZURE_DEVOPS_PAT"]

servers[os.environ["SERVER_NAME"]] = {
    "type": "stdio",
    "command": os.environ["SERVER_COMMAND"],
    "args": [],
    "env": server_env,
    "tools": ["*"],
}

config_path.write_text(json.dumps(config, indent=2) + "\n")
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
      --server-name)
        [[ $# -ge 2 ]] || die "--server-name requires a value"
        SERVER_NAME="$2"
        shift 2
        ;;
      --write-pat)
        WRITE_PAT_TO_MCP_CONFIG=true
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
  install_local_server
  write_mcp_config

  log "Setup complete"
  log "Start 'copilot' and run '/mcp show ${SERVER_NAME}' to verify the server"
}

main "$@"
