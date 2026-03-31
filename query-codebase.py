#!/usr/bin/env python3
"""Query ChromaDB codebase collection. Called by the MCP server."""

import json
import os
import sys

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

CHROMA_PATH = os.environ.get(
    "CHROMA_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "chroma_db")
)
COLLECTION_NAME = "codebase"


def get_collection():
    client = chromadb.PersistentClient(path=os.path.abspath(CHROMA_PATH))
    ef = DefaultEmbeddingFunction()
    return client.get_collection(name=COLLECTION_NAME, embedding_function=ef)


def search(args):
    collection = get_collection()
    query = args["query"]
    limit = args.get("limit", 5)

    where = {}
    if args.get("module"):
        where["module"] = args["module"]
    if args.get("application"):
        where["application"] = args["application"]
    if args.get("file_type"):
        where["file_type"] = args["file_type"]
    if args.get("chunk_type"):
        where["chunk_type"] = args["chunk_type"]
    if args.get("language"):
        where["language"] = args["language"]
    if args.get("file_path_pattern"):
        where["file_path"] = {"$contains": args["file_path_pattern"]}

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


def get_file_chunks(args):
    collection = get_collection()
    file_path = args["file_path"]

    result = collection.get(
        where={"file_path": file_path},
        include=["documents", "metadatas"]
    )

    results = []
    for i in range(len(result["ids"])):
        results.append({
            "id": result["ids"][i],
            "document": result["documents"][i],
            "metadata": result["metadatas"][i],
        })
    results.sort(key=lambda r: r["metadata"].get("line_start", 0))
    return results


def get_module_overview(args):
    collection = get_collection()
    module = args["module"]

    # Also accept application filter
    where = {"module": module}
    if args.get("application"):
        where = {"$and": [{"module": module}, {"application": args["application"]}]}

    result = collection.get(
        where=where,
        include=["metadatas"]
    )

    results = []
    for i in range(len(result["ids"])):
        meta = result["metadatas"][i]
        results.append({
            "id": result["ids"][i],
            "file_path": meta.get("file_path"),
            "chunk_name": meta.get("chunk_name"),
            "chunk_type": meta.get("chunk_type"),
            "file_type": meta.get("file_type"),
            "line_start": meta.get("line_start"),
            "line_end": meta.get("line_end"),
        })
    results.sort(key=lambda r: (r["file_path"] or "", r.get("line_start", 0)))
    return results


COMMANDS = {
    "search": search,
    "file_chunks": get_file_chunks,
    "module_overview": get_module_overview,
}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: query-codebase.py <json_args>"}))
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
