#!/usr/bin/env python3
"""Ingest PR review comments into ChromaDB for semantic search."""

import json
import os
import sys

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

JSONL_PATH = os.environ.get("REVIEW_COMMENTS_OUTPUT",
    os.path.join(os.path.dirname(__file__), "..", "data", "review-comments.jsonl"))
CHROMA_PATH = os.environ.get("CHROMA_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "chroma_db"))
COLLECTION_NAME = "review_comments"
BATCH_SIZE = 100
MAX_DIFF_CHARS = 500


def build_document(record):
    """Build composite document for embedding: [file_path] body [DIFF: truncated]"""
    parts = []
    if record.get("file_path"):
        parts.append(f"[{record['file_path']}]")
    parts.append(record["body"])
    if record.get("diff_hunk"):
        diff = record["diff_hunk"][:MAX_DIFF_CHARS]
        parts.append(f"[DIFF: {diff}]")
    return " ".join(parts)


def build_metadata(record):
    """Extract metadata fields for ChromaDB filtering."""
    meta = {}
    for key in ("type", "pr_number", "pr_title", "pr_url", "ticket",
                 "reviewer", "file_path", "original_line", "created_at",
                 "comment_url", "in_reply_to_id"):
        val = record.get(key)
        if val is not None:
            meta[key] = val
    # ChromaDB metadata values must be str, int, float, or bool
    if "in_reply_to_id" in meta:
        meta["in_reply_to_id"] = int(meta["in_reply_to_id"])
    if "original_line" in meta and meta["original_line"] is not None:
        meta["original_line"] = int(meta["original_line"])
    return meta


def main():
    jsonl_path = os.path.abspath(JSONL_PATH)
    chroma_path = os.path.abspath(CHROMA_PATH)

    if not os.path.exists(jsonl_path):
        print(f"Error: {jsonl_path} not found. Run extract-review-comments.py first.")
        sys.exit(1)

    # Read all records
    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"Loaded {len(records)} records from {jsonl_path}")

    # Initialize ChromaDB
    client = chromadb.PersistentClient(path=chroma_path)
    ef = DefaultEmbeddingFunction()

    # Delete and recreate collection for clean rebuild
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"Deleted existing collection '{COLLECTION_NAME}'")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"description": "PR review comments from BradBissell for aim-myt"}
    )
    print(f"Created collection '{COLLECTION_NAME}' at {chroma_path}")

    # Ingest in batches
    total = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        ids = [str(r["id"]) for r in batch]
        documents = [build_document(r) for r in batch]
        metadatas = [build_metadata(r) for r in batch]

        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        total += len(batch)
        print(f"  Ingested {total}/{len(records)} records...")

    print(f"\nDone! {total} records ingested into '{COLLECTION_NAME}'")
    print(f"Storage: {chroma_path}")

    # Quick verification
    result = collection.query(query_texts=["naming convention"], n_results=3)
    print(f"\nVerification query 'naming convention' returned {len(result['ids'][0])} results:")
    for doc_id, dist, meta in zip(result["ids"][0], result["distances"][0], result["metadatas"][0]):
        print(f"  [{dist:.4f}] {meta.get('ticket', 'N/A')} - {meta.get('file_path', 'N/A')}")


if __name__ == "__main__":
    main()
