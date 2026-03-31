#!/usr/bin/env python3
"""Query Weaviate ReviewComments collection. Called by the MCP server."""

import json
import os
import sys

import weaviate
import weaviate.classes.query as wq

WEAVIATE_HOST = os.environ.get("WEAVIATE_HOST", "localhost")
WEAVIATE_PORT = int(os.environ.get("WEAVIATE_PORT", "8080"))
WEAVIATE_GRPC_PORT = int(os.environ.get("WEAVIATE_GRPC_PORT", "50051"))
COLLECTION_NAME = "ReviewComments"


def get_client():
    return weaviate.connect_to_custom(
        http_host=WEAVIATE_HOST,
        http_port=WEAVIATE_PORT,
        http_secure=False,
        grpc_host=WEAVIATE_HOST,
        grpc_port=WEAVIATE_GRPC_PORT,
        grpc_secure=False,
    )


def obj_to_dict(obj):
    props = {k: v for k, v in obj.properties.items() if k != "content"}
    result = {
        "id": props.get("doc_id", ""),
        "document": obj.properties.get("content", ""),
        "metadata": props,
    }
    if obj.metadata and obj.metadata.distance is not None:
        result["distance"] = obj.metadata.distance
    return result


def search_similar(args):
    client = get_client()
    try:
        collection = client.collections.get(COLLECTION_NAME)
        query = args["query"]
        limit = args.get("limit", 5)

        filters = None
        filter_parts = []
        if args.get("ticket"):
            filter_parts.append(wq.Filter.by_property("ticket").equal(args["ticket"]))
        if args.get("file_path_pattern"):
            filter_parts.append(wq.Filter.by_property("file_path").like(f"*{args['file_path_pattern']}*"))
        if args.get("comment_type"):
            filter_parts.append(wq.Filter.by_property("comment_type").equal(args["comment_type"]))
        if args.get("pr_number"):
            filter_parts.append(wq.Filter.by_property("pr_number").equal(int(args["pr_number"])))

        if filter_parts:
            filters = filter_parts[0]
            for f in filter_parts[1:]:
                filters = filters & f

        results = collection.query.near_text(
            query=query,
            limit=limit,
            filters=filters,
            return_metadata=wq.MetadataQuery(distance=True),
        )
        return [obj_to_dict(obj) for obj in results.objects]
    finally:
        client.close()


def get_patterns_for_file(args):
    client = get_client()
    try:
        collection = client.collections.get(COLLECTION_NAME)
        file_path = args["file_path"]
        limit = args.get("limit", 10)

        results = []
        seen = set()

        # Exact file match
        exact = collection.query.fetch_objects(
            filters=wq.Filter.by_property("file_path").equal(file_path),
            limit=limit,
        )
        for obj in exact.objects:
            d = obj_to_dict(obj)
            d["match_type"] = "exact_file"
            results.append(d)
            seen.add(d["id"])

        # Semantic search
        semantic = collection.query.near_text(
            query=f"review feedback for {file_path}",
            limit=limit,
            return_metadata=wq.MetadataQuery(distance=True),
        )
        for obj in semantic.objects:
            d = obj_to_dict(obj)
            if d["id"] not in seen:
                d["match_type"] = "semantic"
                results.append(d)
                seen.add(d["id"])

        # Extension pattern search
        ext = os.path.splitext(file_path)[1]
        if ext in (".ts", ".vue", ".spec.ts"):
            pattern = collection.query.near_text(
                query=f"code review patterns for {ext.lstrip('.')} files",
                filters=wq.Filter.by_property("file_path").like(f"*{ext}"),
                limit=limit,
                return_metadata=wq.MetadataQuery(distance=True),
            )
            for obj in pattern.objects:
                d = obj_to_dict(obj)
                if d["id"] not in seen:
                    d["match_type"] = "extension_pattern"
                    results.append(d)
                    seen.add(d["id"])

        return results[:limit]
    finally:
        client.close()


def get_ticket_history(args):
    client = get_client()
    try:
        collection = client.collections.get(COLLECTION_NAME)
        ticket = args["ticket"].upper()

        results_obj = collection.query.fetch_objects(
            filters=wq.Filter.by_property("ticket").equal(ticket),
            limit=200,
        )
        results = [obj_to_dict(obj) for obj in results_obj.objects]
        results.sort(key=lambda r: r["metadata"].get("created_at") or "")
        return results
    finally:
        client.close()


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
