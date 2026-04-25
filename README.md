# copilot-ado-skills

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that gives GitHub Copilot (and any other MCP-compatible AI agent) the ability to interact with **Azure DevOps git repositories**.

---

## Features

| Category | Tools |
|---|---|
| **Git operations** | `clone_repository`, `checkout_branch`, `create_branch`, `commit_changes`, `push_changes`, `pull_changes`, `get_status`, `get_diff`, `list_branches`, `get_log` |
| **Pull requests** | `create_pull_request`, `list_pull_requests`, `get_pull_request`, `get_pr_comments`, `reply_to_pr_comment`, `apply_pr_suggestion` |
| **Repository & code search** | `list_repositories`, `search_repositories`, `get_repository`, `search_code`, `get_file_content`, `list_repository_items` |

---

## Requirements

- Python >= 3.10
- An Azure DevOps organisation
- Authentication via **one** of:
  - `az login` (Azure CLI) – recommended for interactive use
  - `az devops configure` (Azure DevOps CLI extension)
  - `AZURE_DEVOPS_PAT` environment variable (Personal Access Token)

---

## Installation

```bash
pip install -e .
```

Or from the published package (once released):

```bash
pip install copilot-ado-skills
```

---

## Authentication

### Option 1 – Azure CLI (recommended)

```bash
az login
```

The skill automatically calls `AzureCliCredential` from `azure-identity` to obtain a bearer token for the Azure DevOps resource ID (`499b84ac-1321-427f-aa17-267ca6975798`).

For git remote operations such as clone, pull, and push, the MCP tools reuse
those credentials non-interactively so git does not stop and wait for a
username/password prompt.

### Option 2 – Personal Access Token

```bash
export AZURE_DEVOPS_PAT="<your-pat>"
```

### Organisation URL

All tools that call the ADO API require your organisation URL.  Set it once via the environment variable:

```bash
export AZURE_DEVOPS_ORG_URL="https://dev.azure.com/<your-org>"
```

Alternatively, pass `organization_url` directly in each tool call.

---

## Running the MCP server

```bash
# After pip install -e .
copilot-ado-skills

# Or directly
python -m ado_git_skill.server
```

The server communicates over **stdio** (standard MCP transport) so it can be registered in any MCP host.

---

## How MCP works with Copilot CLI

### How Copilot CLI finds the server

Copilot CLI does **not** reach out to a URL or a network port to find this server. Instead, it reads a local configuration file at startup:

```
~/.copilot/mcp-config.json   (Linux / macOS)
%USERPROFILE%\.copilot\mcp-config.json   (Windows)
```

Each entry under `"mcpServers"` tells Copilot CLI *how to launch* a server process. For example:

```json
{
  "mcpServers": {
    "ado-git": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "ado_git_skill.server"]
    }
  }
}
```

When Copilot CLI starts, it reads this file and **spawns each registered server as a child process** using the `command` + `args` listed. No network socket or port is involved.

### The `stdio` transport

`"type": "stdio"` means the MCP host (Copilot CLI) and the server communicate through the child process's **standard input and output streams** (stdin/stdout). The server never opens a TCP port; it simply reads JSON messages from stdin and writes JSON responses to stdout. This makes it safe to run entirely locally without exposing any network service.

### End-to-end communication flow

```
User types a prompt in Copilot CLI
         │
         ▼
Copilot CLI reads ~/.copilot/mcp-config.json
  └─ spawns: python3 -m ado_git_skill.server  (child process)
         │
         ▼ MCP JSON-RPC handshake (over stdin/stdout)
  1. initialize          ← Copilot sends capabilities
  2. initialize result   → server replies with its capabilities
  3. tools/list          ← Copilot asks what tools are available
  4. tools/list result   → server returns the list of tool definitions
         │
         ▼ Copilot passes prompt + available tools to the LLM
         │
         ▼ LLM decides a tool is needed (e.g. list_repositories)
  5. tools/call          ← Copilot sends tool name + arguments
  6. tools/call result   → server executes the Azure DevOps API call
                            and returns structured data
         │
         ▼ LLM composes the final answer using the tool result
         │
         ▼
User sees the response in Copilot CLI
```

Steps 5 and 6 repeat for every tool the LLM needs to invoke to answer the prompt. The server process stays alive for the entire Copilot CLI session, so the handshake (steps 1–4) only happens once.

### Why there is no "server URL" to configure

Because the transport is `stdio`, the only thing Copilot needs to know is:

- **which executable to run** (`command` + `args`)
- **which environment variables to set** (`env` block in the config)

The `AZURE_DEVOPS_ORG_URL` and `AZURE_DEVOPS_PAT` values in the `env` block are injected into the server process's environment at launch time, so the server always has the right credentials without you exporting them globally.

---

### GitHub Copilot CLI

You do **not** put this repository in a special Copilot "skills" folder. Since this project is an **MCP server**, you can clone it anywhere on your machine and then register it in Copilot CLI.

#### 1. Clone and install the server locally

```bash
git clone https://github.com/knibel/copilot-ado-skills.git
cd copilot-ado-skills
python3 -m pip install -e .
```

If you are on Windows, replace `python3` with `py`.

#### Ubuntu / Debian helper script

If you want one command that installs the required system dependencies, installs
GitHub Copilot CLI, installs this MCP server into a local virtual environment,
and writes the Copilot CLI MCP configuration automatically, run:

```bash
chmod +x ./scripts/setup-ubuntu.sh
./scripts/setup-ubuntu.sh --org-url "https://dev.azure.com/<your-org>"
```

What the script does:

- checks `python3`, `pip`, `node`, and `npm`
- installs missing Ubuntu/Debian packages with `apt` and falls back to the active version-specific venv package (for example `python3.12-venv`) when needed
- installs Node.js 22.x when the system version is too old for Copilot CLI
- installs GitHub Copilot CLI with `npm install -g @github/copilot` if `copilot` is missing
- creates `.venv` in the repository and runs `pip install -e .`
- writes the MCP entry to `~/.copilot/mcp-config.json` (or `$COPILOT_HOME/mcp-config.json`)

If you want to store a PAT in the Copilot MCP config as well, export it first and
add `--write-pat`:

```bash
export AZURE_DEVOPS_PAT="<your-pat>"
./scripts/setup-ubuntu.sh \
  --org-url "https://dev.azure.com/<your-org>" \
  --write-pat
```

#### 2. Configure Azure DevOps authentication

Use **one** of these options:

```bash
# Option A: Azure CLI login
az login

# Option B: Personal Access Token
export AZURE_DEVOPS_PAT="<your-pat>"
```

Then set your Azure DevOps organization URL:

```bash
export AZURE_DEVOPS_ORG_URL="https://dev.azure.com/<your-org>"
```

#### 3. Register the MCP server in Copilot CLI

Create or edit `~/.copilot/mcp-config.json` and add:

```json
{
  "mcpServers": {
    "ado-git": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "ado_git_skill.server"],
      "env": {
        "AZURE_DEVOPS_ORG_URL": "https://dev.azure.com/<your-org>"
      },
      "tools": ["*"]
    }
  }
}
```

If you want to use a PAT instead of `az login`, include it in the same `env` block:

```json
{
  "mcpServers": {
    "ado-git": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "ado_git_skill.server"],
      "env": {
        "AZURE_DEVOPS_ORG_URL": "https://dev.azure.com/<your-org>",
        "AZURE_DEVOPS_PAT": "<your-pat>"
      },
      "tools": ["*"]
    }
  }
}
```

#### 4. Start Copilot CLI and verify the server

Start Copilot CLI:

```bash
copilot
```

Then run:

```text
/mcp show
```

You should see `ado-git` listed. To inspect it directly:

```text
/mcp show ado-git
```

#### 5. Use it

Once the server is listed, you can prompt Copilot CLI normally, for example:

```text
List the Azure DevOps repositories in project MyProject using the ado-git MCP server.
```

If Copilot CLI asks you to trust the current directory or approve MCP tool usage, approve the repository directory and the `ado-git` server/tools you want to use.

### VS Code / GitHub Copilot (`settings.json`)

```json
{
  "mcp": {
    "servers": {
      "ado-git": {
        "command": "copilot-ado-skills",
        "env": {
          "AZURE_DEVOPS_ORG_URL": "https://dev.azure.com/<your-org>"
        }
      }
    }
  }
}
```

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "ado-git": {
      "command": "copilot-ado-skills",
      "env": {
        "AZURE_DEVOPS_ORG_URL": "https://dev.azure.com/<your-org>"
      }
    }
  }
}
```

---

## Tool reference

### Git operations

#### `clone_repository`
Clone an ADO repository to a local path.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `remote_url` | string | yes | HTTPS or SSH URL of the remote repository |
| `destination` | string | yes | Local directory to clone into |
| `branch` | string | | Branch to check out after cloning |

#### `checkout_branch`
Check out a branch (optionally creating it).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `working_dir` | string | yes | Local repo path |
| `branch` | string | yes | Branch name |
| `create` | boolean | | Create branch if missing (default: false) |

#### `create_branch`
Create a new local branch.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `working_dir` | string | yes | Local repo path |
| `branch` | string | yes | New branch name |
| `base_branch` | string | | Branch to base off (default: current HEAD) |

#### `commit_changes`
Stage and commit local changes.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `working_dir` | string | yes | Local repo path |
| `message` | string | yes | Commit message |
| `add_all` | boolean | | Stage all changes first (default: true) |

#### `push_changes`
Push commits to the ADO remote.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `working_dir` | string | yes | Local repo path |
| `remote` | string | | Remote name (default: origin) |
| `branch` | string | | Branch to push (default: current) |
| `set_upstream` | boolean | | Set upstream tracking (default: true) |

#### `pull_changes`
Pull latest changes from the ADO remote.

#### `get_status`
Get working-tree status (branch, modified, staged, untracked files).

#### `get_diff`
Get a unified diff.

#### `list_branches`
List local and remote branches.

#### `get_log`
Return recent commit history.

---

### Pull requests

#### `create_pull_request`
Create a PR in Azure DevOps (defaults target branch to `main`).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project` | string | yes | ADO project name |
| `repository` | string | yes | Repository name |
| `title` | string | yes | PR title |
| `source_branch` | string | yes | Source branch (must exist on remote) |
| `target_branch` | string | | Target branch (default: main) |
| `description` | string | | PR body |
| `auto_complete` | boolean | | Enable auto-complete (default: false) |
| `draft` | boolean | | Create as draft (default: false) |
| `organization_url` | string | | ADO org URL override |

#### `list_pull_requests`
List PRs in a repository.

#### `get_pull_request`
Get details of a specific PR.

#### `get_pr_comments`
Get all comment threads on a PR, including inline file/line context.

#### `reply_to_pr_comment`
Post a reply to an existing comment thread.

#### `apply_pr_suggestion`
Apply an inline code suggestion from a PR review to the local working tree and commit it.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `working_dir` | string | yes | Local repo path |
| `file_path` | string | yes | Repo-relative path of file to modify |
| `start_line` | integer | yes | First line to replace (1-based) |
| `end_line` | integer | yes | Last line to replace (1-based) |
| `suggested_content` | string | yes | Replacement content |
| `commit_message` | string | | Commit message |

---

### Repository & code search

#### `list_repositories`
List all git repositories in an ADO project.

#### `search_repositories`
Case-insensitive substring search for repositories by name.

#### `get_repository`
Get details of a specific repository.

#### `search_code`
Search source code across ADO repositories via the ADO Search API.  Supports ADO search operators (`ext:py`, `file:main.py`, `repo:my-repo`).

This tool is especially useful when the agent needs to understand existing
implementations before making a change – for example, finding the REST client
for *service XYZ* before writing a new one.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project` | string | yes | ADO project name |
| `query` | string | yes | Search query |
| `repository` | string | | Restrict to repository |
| `top` | integer | | Max results (default: 25) |
| `organization_url` | string | | ADO org URL override |

#### `get_file_content`
Retrieve raw file content from an ADO repository without cloning.

#### `list_repository_items`
List files and directories in a repository path.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v
```

---

## Project structure

```
src/ado_git_skill/
├── __init__.py
├── auth.py           # Azure authentication helpers
├── server.py         # MCP server entry point
└── tools/
    ├── __init__.py
    ├── git_tools.py      # Local git operations (clone, push, pull, ...)
    ├── pr_tools.py       # Pull request CRUD + inline suggestion apply
    └── search_tools.py   # Repository listing & code search

tests/
├── test_auth.py
├── test_git_tools.py
├── test_pr_tools.py
└── test_search_tools.py
```
