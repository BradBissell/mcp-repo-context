#!/usr/bin/env python3
"""Ingest codebase chunks into ChromaDB for semantic code search."""

import json
import os
import sys

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

JSONL_PATH = os.environ.get("CODEBASE_CHUNKS_OUTPUT",
    os.path.join(os.path.dirname(__file__), "..", "data", "codebase-chunks.jsonl"))
CHROMA_PATH = os.environ.get("CHROMA_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "chroma_db"))
COLLECTION_NAME = "codebase"
BATCH_SIZE = 100

# ChromaDB metadata only supports str, int, float, bool
METADATA_FIELDS = (
    "file_path", "chunk_name", "chunk_type", "module",
    "application", "file_type", "language", "line_start", "line_end",
)


def build_metadata(record):
    meta = {}
    for key in METADATA_FIELDS:
        val = record.get(key)
        if val is not None:
            meta[key] = val
    return meta


def main():
    jsonl_path = os.path.abspath(JSONL_PATH)
    chroma_path = os.path.abspath(CHROMA_PATH)

    if not os.path.exists(jsonl_path):
        print(f"Error: {jsonl_path} not found. Run extract-codebase.py first.")
        sys.exit(1)

    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"Loaded {len(records)} chunks from {jsonl_path}")

    client = chromadb.PersistentClient(path=chroma_path)
    ef = DefaultEmbeddingFunction()

    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"Deleted existing collection '{COLLECTION_NAME}'")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"description": "aim-myt source code chunks for semantic search"}
    )
    print(f"Created collection '{COLLECTION_NAME}' at {chroma_path}")

    total = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        ids = [r["id"] for r in batch]
        documents = [r["embedding_text"] for r in batch]
        metadatas = [build_metadata(r) for r in batch]

        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        total += len(batch)
        print(f"  Ingested {total}/{len(records)} chunks...")

    print(f"\nDone! {total} chunks ingested into '{COLLECTION_NAME}'")
    print(f"Storage: {chroma_path}")

    # Verification queries
    for query in ["authentication guard", "shopping cart checkout", "Vue composable for listings"]:
        result = collection.query(query_texts=[query], n_results=3)
        print(f"\nQuery '{query}':")
        for rid, dist, meta in zip(result["ids"][0], result["distances"][0], result["metadatas"][0]):
            print(f"  [{dist:.4f}] {meta.get('file_path', 'N/A')} :: {meta.get('chunk_name', 'N/A')} ({meta.get('chunk_type', '')})")


if __name__ == "__main__":
    main()
