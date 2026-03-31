#!/usr/bin/env python3
"""Query Weaviate Codebase collection. Called by the MCP server."""

import json
import os
import sys

import weaviate
import weaviate.classes.query as wq

WEAVIATE_HOST = os.environ.get("WEAVIATE_HOST", "localhost")
WEAVIATE_PORT = int(os.environ.get("WEAVIATE_PORT", "8080"))
WEAVIATE_GRPC_PORT = int(os.environ.get("WEAVIATE_GRPC_PORT", "50051"))
COLLECTION_NAME = "Codebase"


def get_client():
    return weaviate.connect_to_custom(
        http_host=WEAVIATE_HOST,
        http_port=WEAVIATE_PORT,
        http_secure=False,
        grpc_host=WEAVIATE_HOST,
        grpc_port=WEAVIATE_GRPC_PORT,
        grpc_secure=False,
    )


def obj_to_dict(obj, include_doc=True):
    props = {k: v for k, v in obj.properties.items() if k != "content"}
    result = {
        "id": props.get("doc_id", ""),
        "metadata": props,
    }
    if include_doc:
        result["document"] = obj.properties.get("content", "")
    if obj.metadata and obj.metadata.distance is not None:
        result["distance"] = obj.metadata.distance
    return result


def search(args):
    client = get_client()
    try:
        collection = client.collections.get(COLLECTION_NAME)
        query = args["query"]
        limit = args.get("limit", 5)

        filter_parts = []
        if args.get("module"):
            filter_parts.append(wq.Filter.by_property("module").equal(args["module"]))
        if args.get("application"):
            filter_parts.append(wq.Filter.by_property("application").equal(args["application"]))
        if args.get("file_type"):
            filter_parts.append(wq.Filter.by_property("file_type").equal(args["file_type"]))
        if args.get("chunk_type"):
            filter_parts.append(wq.Filter.by_property("chunk_type").equal(args["chunk_type"]))
        if args.get("language"):
            filter_parts.append(wq.Filter.by_property("language").equal(args["language"]))
        if args.get("file_path_pattern"):
            filter_parts.append(wq.Filter.by_property("file_path").like(f"*{args['file_path_pattern']}*"))

        filters = None
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


def get_file_chunks(args):
    client = get_client()
    try:
        collection = client.collections.get(COLLECTION_NAME)
        file_path = args["file_path"]

        results_obj = collection.query.fetch_objects(
            filters=wq.Filter.by_property("file_path").equal(file_path),
            limit=100,
        )
        results = [obj_to_dict(obj) for obj in results_obj.objects]
        results.sort(key=lambda r: r["metadata"].get("line_start", 0))
        return results
    finally:
        client.close()


def get_module_overview(args):
    client = get_client()
    try:
        collection = client.collections.get(COLLECTION_NAME)
        module = args["module"]

        filter_parts = [wq.Filter.by_property("module").equal(module)]
        if args.get("application"):
            filter_parts.append(wq.Filter.by_property("application").equal(args["application"]))

        filters = filter_parts[0]
        for f in filter_parts[1:]:
            filters = filters & f

        results_obj = collection.query.fetch_objects(
            filters=filters,
            limit=200,
        )
        results = []
        for obj in results_obj.objects:
            d = obj_to_dict(obj, include_doc=False)
            meta = d["metadata"]
            results.append({
                "id": d["id"],
                "file_path": meta.get("file_path"),
                "chunk_name": meta.get("chunk_name"),
                "chunk_type": meta.get("chunk_type"),
                "file_type": meta.get("file_type"),
                "line_start": meta.get("line_start"),
                "line_end": meta.get("line_end"),
            })
        results.sort(key=lambda r: (r["file_path"] or "", r.get("line_start", 0)))
        return results
    finally:
        client.close()


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
