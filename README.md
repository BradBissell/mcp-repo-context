# mcp-repo-context

A ChromaDB-backed MCP server that gives Claude Code agents semantic search over your repository's PR review comments and source code.

## What it does

- **Extracts** PR review comments from GitHub and chunks your source code into functions/classes/types
- **Embeds** everything into ChromaDB using all-MiniLM-L6-v2 (runs locally, no API keys)
- **Serves** 6 MCP tools that Claude Code agents use during peer reviews and solution planning

## MCP Tools

| Tool | Description |
|---|---|
| `search_similar_reviews` | Semantic search across past PR review comments |
| `get_review_patterns_for_file` | Find review feedback related to a specific file |
| `get_ticket_review_history` | All review comments for a JIRA ticket |
| `search_codebase` | Semantic search across source code chunks |
| `get_file_chunks` | Get all functions/classes in a file |
| `get_module_overview` | List all code in a module |

## Quick Start

### Option A: Full extraction (from any repo)

```bash
cd /path/to/your-repo
REVIEW_AUTHORS=reviewer1,reviewer2 /path/to/mcp-repo-context/setup.sh
```

### Option B: Pre-built data (if the repo ships JSONL files)

```bash
cd /path/to/your-repo
/path/to/mcp-repo-context/setup.sh --data-dir ./data
```

This skips GitHub API calls and just ingests the committed JSONL files.

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|---|---|---|
| `GITHUB_REPO` | Auto-detected via `gh` | GitHub repo in `owner/repo` format |
| `REVIEW_AUTHORS` | All humans (exclude bots) | Comma-separated GitHub usernames |
| `TICKET_PATTERN` | `[A-Z]+-\d+` | Regex to extract ticket IDs from PR titles |
| `SOURCE_GLOBS` | `**/*.ts`, `**/*.vue`, `**/*.js` | JSON array of `[label, glob]` pairs |
| `EXCLUDE_DIRS` | `node_modules,dist,...` | Comma-separated dirs to skip |

## Prerequisites

- Docker
- GitHub CLI (`gh`) authenticated
- Claude Code CLI (`claude`)

## How it works

1. `setup.sh` builds a Docker image with Python, Node.js, ChromaDB, and the MCP server
2. It extracts review comments from GitHub and chunks your source code (or ingests pre-built JSONL)
3. Data is stored in a named Docker volume (`<repo>-knowledge-data`)
4. The MCP server runs as a Docker container, communicating via stdio
5. Claude Code agents call the MCP tools during reviews and solution planning
