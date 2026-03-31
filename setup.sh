#!/bin/bash
# Setup the AI knowledge base MCP server for a repository.
#
# Builds the Docker image, extracts/ingests data into ChromaDB,
# and registers the MCP server with Claude Code.
#
# Prerequisites:
#   - Docker
#   - GitHub CLI (gh) authenticated
#   - Claude Code CLI (claude) installed
#
# Usage:
#   # From a target repo directory (full extraction):
#   /path/to/mcp-repo-context/setup.sh
#
#   # With pre-built JSONL data (skip GitHub extraction):
#   /path/to/mcp-repo-context/setup.sh --data-dir /path/to/repo/data
#
#   # With specific reviewers:
#   REVIEW_AUTHORS=BradBissell /path/to/mcp-repo-context/setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(pwd)"
DATA_DIR=""
SKIP_EXTRACT=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --data-dir)
            DATA_DIR="$2"
            SKIP_EXTRACT=true
            shift 2
            ;;
        --repo-dir)
            REPO_DIR="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

REPO_NAME=$(basename "$REPO_DIR")
VOLUME_NAME="${REPO_NAME}-knowledge-data"
IMAGE_NAME="mcp-repo-context"

echo "============================================"
echo "  MCP Repo Context Setup"
echo "  Repository: $REPO_NAME"
echo "============================================"
echo ""

for cmd in docker gh; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: $cmd is not installed."
        exit 1
    fi
done

if ! gh auth status &>/dev/null; then
    echo "Error: gh is not authenticated. Run 'gh auth login' first."
    exit 1
fi

echo "Step 1/3: Building Docker image..."
docker build -t "$IMAGE_NAME" -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR"
echo ""

if [ "$SKIP_EXTRACT" = true ] && [ -n "$DATA_DIR" ]; then
    echo "Step 2/3: Ingesting pre-built data from $DATA_DIR..."
    docker run --rm \
        -v "$(cd "$DATA_DIR" && pwd)":/data:ro \
        -v "$VOLUME_NAME":/app/data \
        -v "$(cd "$REPO_DIR" && pwd)":/repo:ro \
        -e CHROMA_DB_PATH=/app/data/chroma_db \
        -e REVIEW_COMMENTS_OUTPUT=/data/review-comments.jsonl \
        -e CODEBASE_CHUNKS_OUTPUT=/data/codebase-chunks.jsonl \
        -e REPO_ROOT=/repo \
        --entrypoint /bin/bash \
        "$IMAGE_NAME" -c '
            echo "Ingesting review comments..."
            python3 /app/ingest-review-embeddings.py
            echo ""
            echo "Ingesting codebase chunks..."
            python3 /app/ingest-codebase.py
        '
else
    echo "Step 2/3: Extracting and ingesting knowledge..."
    docker run --rm \
        -v "$VOLUME_NAME":/app/data \
        -v "$(cd "$REPO_DIR" && pwd)":/repo:ro \
        -v "${HOME}/.config/gh:/root/.config/gh:ro" \
        -e CHROMA_DB_PATH=/app/data/chroma_db \
        -e REVIEW_COMMENTS_OUTPUT=/app/data/review-comments.jsonl \
        -e CODEBASE_CHUNKS_OUTPUT=/app/data/codebase-chunks.jsonl \
        -e REPO_ROOT=/repo \
        -e GITHUB_REPO="${GITHUB_REPO:-}" \
        -e REVIEW_AUTHORS="${REVIEW_AUTHORS:-}" \
        -e SOURCE_GLOBS="${SOURCE_GLOBS:-}" \
        -e TICKET_PATTERN="${TICKET_PATTERN:-}" \
        --entrypoint /bin/bash \
        "$IMAGE_NAME" -c '
            mkdir -p /app/data
            echo "=== Extracting review comments from GitHub ==="
            python3 /app/extract-review-comments.py
            echo ""
            echo "=== Ingesting review comments ==="
            python3 /app/ingest-review-embeddings.py
            echo ""
            echo "=== Extracting and chunking codebase ==="
            cd /repo && python3 /app/extract-codebase.py
            echo ""
            echo "=== Ingesting codebase ==="
            python3 /app/ingest-codebase.py
        '
fi
echo ""

echo "Step 3/3: Registering MCP server with Claude Code..."
claude mcp remove review-knowledge 2>/dev/null || true

RUN_SCRIPT="$REPO_DIR/.claude/run-mcp-server.sh"
mkdir -p "$(dirname "$RUN_SCRIPT")"
cat > "$RUN_SCRIPT" << EOFSCRIPT
#!/bin/bash
exec docker run --rm -i \\
    -v ${VOLUME_NAME}:/app/data \\
    -e CHROMA_DB_PATH=/app/data/chroma_db \\
    ${IMAGE_NAME}
EOFSCRIPT
chmod +x "$RUN_SCRIPT"

claude mcp add review-knowledge -- "$RUN_SCRIPT"

echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "MCP server registered as 'review-knowledge'"
echo ""
echo "Add these permissions to Claude Code settings:"
echo "  mcp__review-knowledge__search_similar_reviews"
echo "  mcp__review-knowledge__get_review_patterns_for_file"
echo "  mcp__review-knowledge__get_ticket_review_history"
echo "  mcp__review-knowledge__search_codebase"
echo "  mcp__review-knowledge__get_file_chunks"
echo "  mcp__review-knowledge__get_module_overview"
echo ""
echo "To refresh: re-run this script"
