#!/bin/bash
# Setup the AI knowledge base MCP server for a repository.
#
# Checks that Weaviate is running, optionally ingests JSONL data,
# builds the MCP server, and registers it with Claude Code.
#
# Prerequisites:
#   - Weaviate running at WEAVIATE_HOST:WEAVIATE_PORT
#   - Python 3 with pip
#   - Node.js >= 18
#   - Claude Code CLI (claude)
#   - GitHub CLI (gh) — only needed when extracting fresh data
#
# Usage:
#   # Register MCP server (Weaviate already running + ingested):
#   cd /path/to/your-repo
#   ../mcp-repo-context/setup.sh
#
#   # Ingest pre-built JSONL files then register:
#   ../mcp-repo-context/setup.sh --data-dir ./data
#
#   # Extract fresh data from GitHub, ingest, then register:
#   REVIEW_AUTHORS=your-github-username ../mcp-repo-context/setup.sh --extract

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(pwd)"
DATA_DIR=""
DO_EXTRACT=false

WEAVIATE_HOST="${WEAVIATE_HOST:-localhost}"
WEAVIATE_PORT="${WEAVIATE_PORT:-8080}"
WEAVIATE_GRPC_PORT="${WEAVIATE_GRPC_PORT:-50052}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --data-dir) DATA_DIR="$2"; shift 2 ;;
        --extract)  DO_EXTRACT=true; shift ;;
        --repo-dir) REPO_DIR="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

REPO_NAME=$(basename "$REPO_DIR")

echo "============================================"
echo "  MCP Repo Context Setup"
echo "  Repository: $REPO_NAME"
echo "============================================"
echo ""

# --- Step 1: Verify Weaviate is reachable ---
echo "==> Checking Weaviate at http://$WEAVIATE_HOST:$WEAVIATE_PORT..."
if ! curl -sf "http://$WEAVIATE_HOST:$WEAVIATE_PORT/v1/.well-known/ready" > /dev/null; then
    echo ""
    echo "Error: Weaviate is not running at http://$WEAVIATE_HOST:$WEAVIATE_PORT"
    echo ""
    echo "Start a Weaviate instance first (e.g., via docker compose) with the"
    echo "text2vec-transformers module enabled, then re-run this script."
    exit 1
fi
echo "Weaviate is ready."
echo ""

# --- Step 2: Extract fresh data (optional) ---
if [ "$DO_EXTRACT" = true ]; then
    for cmd in gh python3; do
        if ! command -v "$cmd" &>/dev/null; then
            echo "Error: '$cmd' is required for extraction but not found."
            exit 1
        fi
    done

    EXTRACT_OUTPUT="$REPO_DIR/data"
    mkdir -p "$EXTRACT_OUTPUT"

    echo "==> Extracting review comments from GitHub..."
    REVIEW_COMMENTS_OUTPUT="$EXTRACT_OUTPUT/review-comments.jsonl" \
    GITHUB_REPO="${GITHUB_REPO:-}" \
    REVIEW_AUTHORS="${REVIEW_AUTHORS:-}" \
    TICKET_PATTERN="${TICKET_PATTERN:-}" \
        python3 "$SCRIPT_DIR/extract-review-comments.py"

    echo ""
    echo "==> Chunking codebase..."
    CODEBASE_CHUNKS_OUTPUT="$EXTRACT_OUTPUT/codebase-chunks.jsonl" \
    REPO_ROOT="$REPO_DIR" \
    SOURCE_GLOBS="${SOURCE_GLOBS:-}" \
        python3 "$SCRIPT_DIR/extract-codebase.py"

    DATA_DIR="$EXTRACT_OUTPUT"
fi

# --- Step 3: Ingest JSONL into Weaviate (optional) ---
if [ -n "$DATA_DIR" ]; then
    echo "==> Ingesting JSONL data from $DATA_DIR into Weaviate..."
    WEAVIATE_URL="http://$WEAVIATE_HOST:$WEAVIATE_PORT" \
    WEAVIATE_GRPC_PORT="$WEAVIATE_GRPC_PORT" \
    DATA_DIR="$DATA_DIR" \
        python3 "$SCRIPT_DIR/ingest.py"
    echo ""
fi

# --- Step 4: Install Python dependencies ---
echo "==> Installing Python dependencies..."
# Try a plain install first. Fall back to --break-system-packages on PEP 668
# distros (Debian 12+, Ubuntu 23.04+) where system Python is externally managed.
if ! pip install -q weaviate-client 2>/dev/null; then
    pip install -q --break-system-packages weaviate-client
fi
echo ""

# --- Step 5: Build MCP server ---
echo "==> Building MCP server..."
cd "$SCRIPT_DIR/mcp-server"
npm install --silent
npm run build --silent
cd "$SCRIPT_DIR"
echo ""

# --- Step 6: Register with Claude Code ---
# Write to .mcp.json in the target repo (project scope). Claude Code auto-
# discovers .mcp.json from cwd up the ancestor chain at session start. The
# `-s user` scope writes to a location some Claude Code versions do not read,
# so project scope is the reliable cross-version choice.
echo "==> Registering MCP server with Claude Code..."
cd "$REPO_DIR"
claude mcp remove review-knowledge 2>/dev/null || true
claude mcp add review-knowledge -s project \
    -e WEAVIATE_HOST="$WEAVIATE_HOST" \
    -e WEAVIATE_PORT="$WEAVIATE_PORT" \
    -e WEAVIATE_GRPC_PORT="$WEAVIATE_GRPC_PORT" \
    -e REVIEW_QUERY_SCRIPT_PATH="$SCRIPT_DIR/query-review-knowledge.py" \
    -e CODEBASE_QUERY_SCRIPT_PATH="$SCRIPT_DIR/query-codebase.py" \
    -- node "$SCRIPT_DIR/mcp-server/build/index.js"
echo ""
echo "Wrote MCP config to: $REPO_DIR/.mcp.json"
echo "Add this file to .gitignore if you do not want it committed."
echo ""

echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "MCP server 'review-knowledge' registered."
echo ""
echo "Add these to Claude Code permissions (Settings > Permissions > Allow):"
echo "  mcp__review-knowledge__search_similar_reviews"
echo "  mcp__review-knowledge__get_review_patterns_for_file"
echo "  mcp__review-knowledge__get_ticket_review_history"
echo "  mcp__review-knowledge__search_codebase"
echo "  mcp__review-knowledge__get_file_chunks"
echo "  mcp__review-knowledge__get_module_overview"
echo ""
echo "Restart Claude Code to load the new MCP server."
