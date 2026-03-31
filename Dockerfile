FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gpg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp-server/ ./mcp-server/
RUN cd mcp-server && npm install && npm run build

COPY extract-review-comments.py .
COPY extract-codebase.py .
COPY ingest-review-embeddings.py .
COPY ingest-codebase.py .
COPY query-review-knowledge.py .
COPY query-codebase.py .

RUN mkdir -p /app/data /repo

ENV CHROMA_DB_PATH=/app/data/chroma_db
ENV REVIEW_QUERY_SCRIPT_PATH=/app/query-review-knowledge.py
ENV CODEBASE_QUERY_SCRIPT_PATH=/app/query-codebase.py

ENTRYPOINT ["node", "/app/mcp-server/build/index.js"]
