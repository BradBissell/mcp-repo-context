#!/usr/bin/env python3
"""Ingest pre-built JSONL data into Weaviate.

Environment variables:
    WEAVIATE_URL       - Full Weaviate HTTP URL (default: http://localhost:8080)
    WEAVIATE_GRPC_PORT - Weaviate gRPC port (default: 50052)
    DATA_DIR           - Directory containing JSONL files (default: ./data)
"""

import json
import os
import sys
import time
from urllib.parse import urlparse

import weaviate
import weaviate.classes.config as wc

WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "http://localhost:8080")
WEAVIATE_GRPC_PORT = int(os.environ.get("WEAVIATE_GRPC_PORT", "50052"))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))

REVIEW_FIELDS = [
    wc.Property(name="doc_id", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="content", data_type=wc.DataType.TEXT),
    wc.Property(name="comment_type", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="pr_number", data_type=wc.DataType.INT, skip_vectorization=True),
    wc.Property(name="pr_title", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="pr_url", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="ticket", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="reviewer", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="file_path", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="original_line", data_type=wc.DataType.INT, skip_vectorization=True),
    wc.Property(name="created_at", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="comment_url", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="in_reply_to_id", data_type=wc.DataType.INT, skip_vectorization=True),
    wc.Property(name="diff_hunk", data_type=wc.DataType.TEXT, skip_vectorization=True),
]

CODEBASE_FIELDS = [
    wc.Property(name="doc_id", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="content", data_type=wc.DataType.TEXT),
    wc.Property(name="file_path", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="chunk_name", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="chunk_type", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="module", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="application", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="file_type", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="language", data_type=wc.DataType.TEXT, skip_vectorization=True),
    wc.Property(name="line_start", data_type=wc.DataType.INT, skip_vectorization=True),
    wc.Property(name="line_end", data_type=wc.DataType.INT, skip_vectorization=True),
]


def wait_for_weaviate(url, timeout=120):
    print(f"Waiting for Weaviate at {url}...")
    parsed = urlparse(url)
    http_secure = parsed.scheme == "https"
    http_host = parsed.hostname
    http_port = parsed.port or (443 if http_secure else 80)

    start = time.time()
    last_error = None
    while time.time() - start < timeout:
        try:
            client = weaviate.connect_to_custom(
                http_host=http_host,
                http_port=http_port,
                http_secure=http_secure,
                grpc_host=http_host,
                grpc_port=WEAVIATE_GRPC_PORT,
                grpc_secure=http_secure,
            )
            if client.is_ready():
                print("Weaviate is ready.")
                return client
            client.close()
        except Exception as e:
            last_error = e
        time.sleep(2)
    print(f"Timeout waiting for Weaviate. Last error: {last_error}")
    sys.exit(1)


def build_review_content(record):
    parts = []
    if record.get("file_path"):
        parts.append(f"[{record['file_path']}]")
    parts.append(record["body"])
    return " ".join(parts)


def ingest_reviews(client, jsonl_path):
    with open(jsonl_path) as f:
        records = [json.loads(l) for l in f if l.strip()]
    print(f"Loaded {len(records)} review comments")

    if client.collections.exists("ReviewComments"):
        client.collections.delete("ReviewComments")

    collection = client.collections.create(
        name="ReviewComments",
        vector_config=wc.Configure.NamedVectors.text2vec_transformers(name="default"),
        properties=REVIEW_FIELDS,
    )

    with collection.batch.fixed_size(batch_size=100) as batch:
        for i, r in enumerate(records):
            props = {
                "doc_id": str(r["id"]),
                "content": build_review_content(r),
                "comment_type": r.get("type", ""),
                "pr_number": r.get("pr_number", 0),
                "pr_title": r.get("pr_title", ""),
                "pr_url": r.get("pr_url", ""),
                "ticket": r.get("ticket", ""),
                "reviewer": r.get("reviewer", ""),
                "file_path": r.get("file_path", ""),
                "original_line": r.get("original_line") or 0,
                "created_at": r.get("created_at", ""),
                "comment_url": r.get("comment_url", ""),
                "in_reply_to_id": r.get("in_reply_to_id") or 0,
                "diff_hunk": r.get("diff_hunk", ""),
            }
            batch.add_object(properties=props)
            if (i + 1) % 500 == 0:
                print(f"  ReviewComments: {i + 1}/{len(records)}")

    count = collection.aggregate.over_all(total_count=True).total_count
    if count != len(records):
        raise RuntimeError(
            f"ReviewComments ingest incomplete: expected {len(records)}, stored {count}"
        )
    print(f"Done: ReviewComments = {count} records")


def ingest_codebase(client, jsonl_path):
    with open(jsonl_path) as f:
        records = [json.loads(l) for l in f if l.strip()]
    print(f"Loaded {len(records)} codebase chunks")

    if client.collections.exists("Codebase"):
        client.collections.delete("Codebase")

    collection = client.collections.create(
        name="Codebase",
        vector_config=wc.Configure.NamedVectors.text2vec_transformers(name="default"),
        properties=CODEBASE_FIELDS,
    )

    with collection.batch.fixed_size(batch_size=100) as batch:
        for i, r in enumerate(records):
            props = {
                "doc_id": r["id"],
                "content": r["embedding_text"],
                "file_path": r.get("file_path", ""),
                "chunk_name": r.get("chunk_name", ""),
                "chunk_type": r.get("chunk_type", ""),
                "module": r.get("module", ""),
                "application": r.get("application", ""),
                "file_type": r.get("file_type", ""),
                "language": r.get("language", ""),
                "line_start": r.get("line_start", 0),
                "line_end": r.get("line_end", 0),
            }
            batch.add_object(properties=props)
            if (i + 1) % 500 == 0:
                print(f"  Codebase: {i + 1}/{len(records)}")

    count = collection.aggregate.over_all(total_count=True).total_count
    if count != len(records):
        raise RuntimeError(
            f"Codebase ingest incomplete: expected {len(records)}, stored {count}"
        )
    print(f"Done: Codebase = {count} records")


def main():
    client = wait_for_weaviate(WEAVIATE_URL)
    try:
        reviews_path = os.path.join(DATA_DIR, "review-comments.jsonl")
        if os.path.exists(reviews_path):
            ingest_reviews(client, reviews_path)
        else:
            print(f"Skipping reviews: {reviews_path} not found")

        codebase_path = os.path.join(DATA_DIR, "codebase-chunks.jsonl")
        if os.path.exists(codebase_path):
            ingest_codebase(client, codebase_path)
        else:
            print(f"Skipping codebase: {codebase_path} not found")
    finally:
        client.close()


if __name__ == "__main__":
    main()
