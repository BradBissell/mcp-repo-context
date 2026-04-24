# mcp-repo-context

A Weaviate-backed MCP server that gives Claude Code agents semantic search over your repository's PR review comments and source code.

## What it does

- **Extracts** PR review comments from GitHub and chunks your source code into functions/classes/types
- **Embeds** everything into Weaviate via the `text2vec-transformers` module (runs locally, no API keys)
- **Serves** 6 MCP tools that Claude Code agents can call during peer reviews and solution planning

## MCP Tools

| Tool | Description |
|---|---|
| `search_similar_reviews` | Semantic search across past PR review comments |
| `get_review_patterns_for_file` | Find review feedback related to a specific file |
| `get_ticket_review_history` | All review comments for a specific ticket |
| `search_codebase` | Semantic search across source code chunks |
| `get_file_chunks` | Get all functions/classes in a file |
| `get_module_overview` | List all code in a module |

## Prerequisites

- **Weaviate** running with the `text2vec-transformers` module enabled and reachable at `WEAVIATE_HOST:WEAVIATE_PORT` (defaults: `localhost:8080` HTTP, `localhost:50052` gRPC). Any deployment works — a standalone `docker compose` stack, a hosted instance, etc.
- **Python 3** with `pip` (needs `weaviate-client>=4.0.0`)
- **Node.js** >= 18
- **Claude Code CLI** (`claude`)
- **GitHub CLI** (`gh`), authenticated — only required if you extract fresh review data

## Quick Start

The setup script is designed to be run from the root of the repo you want to index. It verifies Weaviate connectivity, optionally ingests data, builds the MCP server, and registers it with Claude Code.

### Option A: Register against already-ingested Weaviate

```bash
cd /path/to/your-repo
/path/to/mcp-repo-context/setup.sh
```

### Option B: Ingest pre-built JSONL first, then register

```bash
cd /path/to/your-repo
/path/to/mcp-repo-context/setup.sh --data-dir ./data
```

The `--data-dir` flag points at a directory containing `review-comments.jsonl` and/or `codebase-chunks.jsonl` (schema is defined by `ingest.py`).

### Option C: Extract fresh data from GitHub, ingest, then register

```bash
cd /path/to/your-repo
REVIEW_AUTHORS=your-github-username /path/to/mcp-repo-context/setup.sh --extract
```

This runs `extract-review-comments.py` and `extract-codebase.py` against the current repo, writes JSONL into `./data/`, ingests into Weaviate, and registers the MCP server.

## Configuration

All scripts read configuration from environment variables.

### Weaviate connection

| Variable | Default | Description |
|---|---|---|
| `WEAVIATE_HOST` | `localhost` | Weaviate host |
| `WEAVIATE_PORT` | `8080` | Weaviate HTTP port |
| `WEAVIATE_GRPC_PORT` | `50052` | Weaviate gRPC port |

### Extraction (when using `--extract`)

| Variable | Default | Description |
|---|---|---|
| `GITHUB_REPO` | Auto-detected via `gh` | GitHub repo in `owner/repo` format |
| `REVIEW_AUTHORS` | All humans (bots excluded) | Comma-separated GitHub usernames to include |
| `TICKET_PATTERN` | `[A-Z]+-\d+` | Regex to extract ticket IDs from PR titles |
| `SOURCE_GLOBS` | `**/*.ts`, `**/*.vue`, `**/*.js` | JSON array of `[label, glob]` pairs |
| `EXCLUDE_DIRS` | `node_modules,dist,...` | Comma-separated directories to skip |

## How it works

1. **Weaviate stores the data.** Two collections are created by `ingest.py` — one for review comments, one for codebase chunks. Vectors are generated at ingest time by Weaviate's `text2vec-transformers` module, so no embeddings live in the JSONL.
2. **Extraction is optional.** The repo ships with `extract-review-comments.py` and `extract-codebase.py` for generating JSONL from scratch, but you can also hand-author JSONL files if you already have the data.
3. **The MCP server runs on the host.** `setup.sh` runs `npm install && npm run build` against `mcp-server/` and registers the compiled `build/index.js` with Claude Code via `claude mcp add`. No Docker is required for the server itself.
4. **Queries go through a Python bridge.** The Node MCP server spawns `query-review-knowledge.py` / `query-codebase.py` via `execFile`, passing JSON args and reading JSON results from stdout. This keeps the Weaviate client in Python while the MCP protocol is served over stdio from Node.

## After setup

The setup script registers an MCP server named `review-knowledge`. To use its tools in Claude Code, allowlist the tool IDs in your Claude Code permissions:

```
mcp__review-knowledge__search_similar_reviews
mcp__review-knowledge__get_review_patterns_for_file
mcp__review-knowledge__get_ticket_review_history
mcp__review-knowledge__search_codebase
mcp__review-knowledge__get_file_chunks
mcp__review-knowledge__get_module_overview
```

Then restart Claude Code. Verify registration with `claude mcp list`.

## License

MIT — see [LICENSE](./LICENSE).
