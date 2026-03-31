#!/usr/bin/env python3
"""Query ChromaDB review knowledge base. Called by the MCP server."""

import json
import os
import sys

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

CHROMA_PATH = os.environ.get(
    "CHROMA_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "chroma_db")
)
COLLECTION_NAME = "review_comments"


def get_collection():
    client = chromadb.PersistentClient(path=os.path.abspath(CHROMA_PATH))
    ef = DefaultEmbeddingFunction()
    return client.get_collection(name=COLLECTION_NAME, embedding_function=ef)


def search_similar(args):
    collection = get_collection()
    query = args["query"]
    limit = args.get("limit", 5)

    where = {}
    if args.get("ticket"):
        where["ticket"] = args["ticket"]
    if args.get("file_path_pattern"):
        where["file_path"] = {"$contains": args["file_path_pattern"]}
    if args.get("comment_type"):
        where["type"] = args["comment_type"]
    if args.get("pr_number"):
        where["pr_number"] = int(args["pr_number"])

    # ChromaDB needs None or a dict with at least one key
    where_filter = where if where else None

    result = collection.query(
        query_texts=[query],
        n_results=limit,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )

    results = []
    for i in range(len(result["ids"][0])):
        results.append({
            "id": result["ids"][0][i],
            "distance": result["distances"][0][i],
            "document": result["documents"][0][i],
            "metadata": result["metadatas"][0][i],
        })
    return results


def get_patterns_for_file(args):
    collection = get_collection()
    file_path = args["file_path"]
    limit = args.get("limit", 10)

    # Extract file extension and directory for broader pattern matching
    ext = os.path.splitext(file_path)[1]  # e.g. ".ts"
    parts = file_path.split("/")

    # Search by exact path first, then by extension pattern
    results = []

    # Try exact file path match
    try:
        exact = collection.get(
            where={"file_path": file_path},
            include=["documents", "metadatas"]
        )
        for i in range(len(exact["ids"])):
            results.append({
                "id": exact["ids"][i],
                "match_type": "exact_file",
                "document": exact["documents"][i],
                "metadata": exact["metadatas"][i],
            })
    except Exception:
        pass

    # Semantic search using the file path as query to find similar files
    semantic = collection.query(
        query_texts=[f"review feedback for {file_path}"],
        n_results=limit,
        include=["documents", "metadatas", "distances"]
    )
    seen_ids = {r["id"] for r in results}
    for i in range(len(semantic["ids"][0])):
        rid = semantic["ids"][0][i]
        if rid not in seen_ids:
            results.append({
                "id": rid,
                "match_type": "semantic",
                "distance": semantic["distances"][0][i],
                "document": semantic["documents"][0][i],
                "metadata": semantic["metadatas"][0][i],
            })

    # Also search by file extension pattern if it's a common type
    if ext in (".ts", ".vue", ".spec.ts"):
        suffix = ext.lstrip(".")
        pattern_results = collection.query(
            query_texts=[f"code review patterns for {suffix} files"],
            n_results=limit,
            where={"file_path": {"$contains": ext}},
            include=["documents", "metadatas", "distances"]
        )
        for i in range(len(pattern_results["ids"][0])):
            rid = pattern_results["ids"][0][i]
            if rid not in seen_ids:
                seen_ids.add(rid)
                results.append({
                    "id": rid,
                    "match_type": "extension_pattern",
                    "distance": pattern_results["distances"][0][i],
                    "document": pattern_results["documents"][0][i],
                    "metadata": pattern_results["metadatas"][0][i],
                })

    return results[:limit]


def get_ticket_history(args):
    collection = get_collection()
    ticket = args["ticket"].upper()

    result = collection.get(
        where={"ticket": ticket},
        include=["documents", "metadatas"]
    )

    results = []
    for i in range(len(result["ids"])):
        results.append({
            "id": result["ids"][i],
            "document": result["documents"][i],
            "metadata": result["metadatas"][i],
        })

    # Sort by created_at
    results.sort(key=lambda r: r["metadata"].get("created_at", ""))
    return results


COMMANDS = {
    "search": search_similar,
    "patterns": get_patterns_for_file,
    "history": get_ticket_history,
}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: query-review-knowledge.py <json_args>"}))
        sys.exit(1)

    try:
        input_data = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)

    command = input_data.get("command")
    if command not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {command}. Valid: {list(COMMANDS.keys())}"}))
        sys.exit(1)

    try:
        results = COMMANDS[command](input_data)
        print(json.dumps({"success": True, "results": results, "count": len(results)}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
