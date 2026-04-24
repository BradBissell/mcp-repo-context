#!/usr/bin/env python3
"""Extract and chunk source code into JSONL for Weaviate ingestion.

Environment variables:
    REPO_ROOT              - Path to the repository root (default: parent of this script)
    CODEBASE_CHUNKS_OUTPUT - Output JSONL path (default: data/codebase-chunks.jsonl)
    SOURCE_GLOBS           - JSON array of [label, glob] pairs (default: auto-detect *.ts, *.vue, *.js, *.py)
    EXCLUDE_DIRS           - Comma-separated directory names to exclude (default: node_modules,dist,...)
"""

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("REPO_ROOT", Path(__file__).parent))
OUTPUT_FILE = Path(os.environ.get("CODEBASE_CHUNKS_OUTPUT",
    str(REPO_ROOT / "data" / "codebase-chunks.jsonl")))
MAX_EMBEDDING_CHARS = 2000

_globs_env = os.environ.get("SOURCE_GLOBS", "")
if _globs_env:
    SOURCE_GLOBS = [(g[0], g[1]) for g in json.loads(_globs_env)]
else:
    # Auto-detect: index all TypeScript, Vue, and JavaScript files
    SOURCE_GLOBS = [
        ("src", "**/*.ts"),
        ("src", "**/*.vue"),
        ("src", "**/*.js"),
    ]

_exclude_env = os.environ.get("EXCLUDE_DIRS", "")
EXCLUDE_DIRS = set(
    d.strip() for d in _exclude_env.split(",") if d.strip()
) if _exclude_env else {
    "node_modules", "dist", ".nuxt", ".output", "coverage",
    ".cache", "e2e", "build", "playwright-report", "test-results",
}

# Regex patterns for TypeScript chunking
DECORATED_CLASS_RE = re.compile(
    r'^(@(?:Controller|Injectable|Module|Guard|Interceptor|Pipe|Schema|Processor)\([^)]*\)\s*\n)'
    r'export\s+(?:default\s+)?class\s+(\w+)',
    re.MULTILINE
)
EXPORT_CLASS_RE = re.compile(
    r'^export\s+(?:default\s+)?(?:abstract\s+)?class\s+(\w+)',
    re.MULTILINE
)
EXPORT_FUNCTION_RE = re.compile(
    r'^export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)',
    re.MULTILINE
)
EXPORT_CONST_RE = re.compile(
    r'^export\s+(?:const|let)\s+(\w+)\s*[:=]',
    re.MULTILINE
)
EXPORT_TYPE_RE = re.compile(
    r'^export\s+(?:type|interface|enum)\s+(\w+)',
    re.MULTILINE
)
IMPORT_BLOCK_RE = re.compile(
    r'^(?:import\s+.+?[;\n])+',
    re.MULTILINE
)
VUE_SCRIPT_RE = re.compile(
    r'<script[^>]*>(.*?)</script>',
    re.DOTALL
)
VUE_TEMPLATE_RE = re.compile(
    r'<template>(.*?)</template>',
    re.DOTALL
)


def should_exclude(filepath: Path) -> bool:
    parts = filepath.parts
    return any(excluded in parts for excluded in EXCLUDE_DIRS)


def classify_file(filepath: str) -> tuple:
    """Returns (file_type, language)."""
    is_test = filepath.endswith(('.spec.ts', '.test.ts'))
    file_type = "test" if is_test else "source"

    if filepath.endswith('.vue'):
        language = "vue"
    elif filepath.endswith('.js'):
        language = "javascript"
    else:
        language = "typescript"

    return file_type, language


def extract_module(filepath: str, application: str) -> str:
    """Extract module name from file path."""
    if application == "api":
        # applications/api/src/auth/auth.guard.ts -> auth
        parts = filepath.replace("applications/api/src/", "").split("/")
        return parts[0] if len(parts) > 1 else "root"
    else:
        # applications/ui/components/messages/MessageList.vue -> components/messages
        parts = filepath.replace("applications/ui/", "").split("/")
        if len(parts) > 2:
            return "/".join(parts[:2])
        elif len(parts) > 1:
            return parts[0]
        return "root"


def find_brace_end(content: str, start: int) -> int:
    """Find the matching closing brace from start position."""
    depth = 0
    i = start
    while i < len(content):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(content)


def extract_chunk_body(content: str, match_start: int) -> tuple:
    """Extract the full body of a chunk starting from a match position.
    Returns (body_text, end_position)."""
    # Find the opening brace
    brace_pos = content.find('{', match_start)
    if brace_pos == -1:
        # No brace — could be a type/interface or single-line export
        # Find the end of the statement (next semicolon or double newline)
        semi_pos = content.find(';', match_start)
        if semi_pos != -1:
            return content[match_start:semi_pos + 1], semi_pos + 1
        nl_pos = content.find('\n\n', match_start)
        if nl_pos != -1:
            return content[match_start:nl_pos], nl_pos
        return content[match_start:], len(content)

    # Check if there's a significant gap (another export in between)
    between = content[match_start:brace_pos]
    if '\nexport ' in between:
        # The brace belongs to something else
        end = content.find('\n\n', match_start)
        if end == -1:
            end = content.find('\n', match_start + 1)
        if end == -1:
            end = len(content)
        return content[match_start:end], end

    end = find_brace_end(content, brace_pos)
    return content[match_start:end], end


def chunk_typescript(content: str, filepath: str, application: str) -> list:
    """Split TypeScript content into function/class/type chunks."""
    chunks = []
    file_type, language = classify_file(filepath)
    module = extract_module(filepath, application)
    lines = content.split('\n')

    def line_number(pos):
        return content[:pos].count('\n') + 1

    # Track which regions are already claimed
    claimed = set()

    def claim_range(start, end):
        for i in range(start, min(end, len(content))):
            claimed.add(i)

    def is_claimed(pos):
        return pos in claimed

    # 1. Find decorated classes (NestJS)
    for match in DECORATED_CLASS_RE.finditer(content):
        if is_claimed(match.start()):
            continue
        decorator = match.group(1).strip()
        class_name = match.group(2)
        body, end_pos = extract_chunk_body(content, match.start())
        claim_range(match.start(), end_pos)
        ln_start = line_number(match.start())
        ln_end = line_number(end_pos)
        chunks.append({
            "chunk_name": class_name,
            "chunk_type": "class",
            "line_start": ln_start,
            "line_end": ln_end,
            "content": body,
        })

    # 2. Find export classes
    for match in EXPORT_CLASS_RE.finditer(content):
        if is_claimed(match.start()):
            continue
        class_name = match.group(1)
        # Check if there's a decorator above
        pre = content[max(0, match.start() - 200):match.start()]
        if re.search(r'@\w+\([^)]*\)\s*$', pre):
            dec_start = content.rfind('@', max(0, match.start() - 200), match.start())
            body, end_pos = extract_chunk_body(content, dec_start)
            claim_range(dec_start, end_pos)
            ln_start = line_number(dec_start)
        else:
            body, end_pos = extract_chunk_body(content, match.start())
            claim_range(match.start(), end_pos)
            ln_start = line_number(match.start())
        ln_end = line_number(end_pos)
        chunks.append({
            "chunk_name": class_name,
            "chunk_type": "class",
            "line_start": ln_start,
            "line_end": ln_end,
            "content": body,
        })

    # 3. Find export functions
    for match in EXPORT_FUNCTION_RE.finditer(content):
        if is_claimed(match.start()):
            continue
        func_name = match.group(1)
        body, end_pos = extract_chunk_body(content, match.start())
        claim_range(match.start(), end_pos)
        chunks.append({
            "chunk_name": func_name,
            "chunk_type": "function",
            "line_start": line_number(match.start()),
            "line_end": line_number(end_pos),
            "content": body,
        })

    # 4. Find export const/let (arrow functions, composables, constants)
    for match in EXPORT_CONST_RE.finditer(content):
        if is_claimed(match.start()):
            continue
        const_name = match.group(1)
        body, end_pos = extract_chunk_body(content, match.start())
        claim_range(match.start(), end_pos)
        # Determine if it's an arrow function or a constant
        ctype = "function" if "=>" in body[:500] or "function" in body[:200] else "constant"
        chunks.append({
            "chunk_name": const_name,
            "chunk_type": ctype,
            "line_start": line_number(match.start()),
            "line_end": line_number(end_pos),
            "content": body,
        })

    # 5. Find export types/interfaces/enums
    for match in EXPORT_TYPE_RE.finditer(content):
        if is_claimed(match.start()):
            continue
        type_name = match.group(1)
        body, end_pos = extract_chunk_body(content, match.start())
        claim_range(match.start(), end_pos)
        chunks.append({
            "chunk_name": type_name,
            "chunk_type": "type",
            "line_start": line_number(match.start()),
            "line_end": line_number(end_pos),
            "content": body,
        })

    # 6. Deduplicate by chunk_name (decorated class + export class can match same thing)
    seen_names = {}
    deduped = []
    for chunk in chunks:
        name = chunk["chunk_name"]
        if name in seen_names:
            # Keep the larger chunk
            existing = seen_names[name]
            if len(chunk["content"]) > len(existing["content"]):
                deduped.remove(existing)
                deduped.append(chunk)
                seen_names[name] = chunk
        else:
            seen_names[name] = chunk
            deduped.append(chunk)
    chunks = deduped

    # 7. If no chunks found, treat whole file as one chunk
    if not chunks:
        chunks.append({
            "chunk_name": Path(filepath).stem,
            "chunk_type": "file",
            "line_start": 1,
            "line_end": len(lines),
            "content": content,
        })

    return chunks


def chunk_vue(content: str, filepath: str, application: str) -> list:
    """Split Vue SFC into script and template chunks."""
    chunks = []

    # Extract and chunk script block
    script_match = VUE_SCRIPT_RE.search(content)
    if script_match:
        script_content = script_match.group(1).strip()
        script_chunks = chunk_typescript(script_content, filepath, application)
        # Adjust line numbers for script offset
        script_start_line = content[:script_match.start(1)].count('\n') + 1
        for chunk in script_chunks:
            chunk["line_start"] += script_start_line
            chunk["line_end"] += script_start_line
            chunks.append(chunk)

    # Extract template as one chunk
    template_match = VUE_TEMPLATE_RE.search(content)
    if template_match:
        template_content = template_match.group(1).strip()
        if template_content:
            template_start = content[:template_match.start(1)].count('\n') + 1
            template_end = template_start + template_content.count('\n')
            chunks.append({
                "chunk_name": f"{Path(filepath).stem}_template",
                "chunk_type": "template",
                "line_start": template_start,
                "line_end": template_end,
                "content": template_content,
            })

    # Fallback
    if not chunks:
        chunks.append({
            "chunk_name": Path(filepath).stem,
            "chunk_type": "file",
            "line_start": 1,
            "line_end": content.count('\n') + 1,
            "content": content,
        })

    return chunks


def build_embedding_text(filepath: str, chunk_name: str, chunk_type: str, content: str) -> str:
    """Build the text that will be embedded."""
    prefix = f"[{filepath} :: {chunk_name} ({chunk_type})]"
    text = f"{prefix} {content}"
    if len(text) > MAX_EMBEDDING_CHARS:
        text = text[:MAX_EMBEDDING_CHARS]
    return text


def extract_imports(content: str) -> list:
    """Extract import sources from content."""
    imports = []
    for match in re.finditer(r"from\s+['\"]([^'\"]+)['\"]", content):
        imports.append(match.group(1))
    return imports


def main():
    os.makedirs(REPO_ROOT / "data", exist_ok=True)
    total_chunks = 0
    total_files = 0
    stats = {"by_type": {}, "by_app": {}, "by_chunk_type": {}}

    with open(OUTPUT_FILE, "w") as f:
        for application, glob_pattern in SOURCE_GLOBS:
            for filepath in sorted(REPO_ROOT.glob(glob_pattern)):
                rel_path = str(filepath.relative_to(REPO_ROOT))

                if should_exclude(filepath):
                    continue

                try:
                    content = filepath.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    print(f"  Warning: Could not read {rel_path}: {e}")
                    continue

                if not content.strip():
                    continue

                total_files += 1
                file_type, language = classify_file(rel_path)
                module = extract_module(rel_path, application)
                file_imports = extract_imports(content)

                # Chunk based on language
                if language == "vue":
                    chunks = chunk_vue(content, rel_path, application)
                else:
                    chunks = chunk_typescript(content, rel_path, application)

                for chunk in chunks:
                    chunk_id = f"{rel_path}::{chunk['chunk_name']}"
                    embedding_text = build_embedding_text(
                        rel_path, chunk["chunk_name"],
                        chunk["chunk_type"], chunk["content"]
                    )

                    record = {
                        "id": chunk_id,
                        "file_path": rel_path,
                        "chunk_name": chunk["chunk_name"],
                        "chunk_type": chunk["chunk_type"],
                        "module": module,
                        "application": application,
                        "file_type": file_type,
                        "language": language,
                        "line_start": chunk["line_start"],
                        "line_end": chunk["line_end"],
                        "content": chunk["content"],
                        "embedding_text": embedding_text,
                    }

                    f.write(json.dumps(record) + "\n")
                    total_chunks += 1

                    # Stats
                    stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1
                    stats["by_app"][application] = stats["by_app"].get(application, 0) + 1
                    ct = chunk["chunk_type"]
                    stats["by_chunk_type"][ct] = stats["by_chunk_type"].get(ct, 0) + 1

                if total_files % 100 == 0:
                    print(f"  Processed {total_files} files, {total_chunks} chunks...")

    print(f"\nDone! Extracted {total_chunks} chunks from {total_files} files")
    print(f"Output: {OUTPUT_FILE}")

    print(f"\nBy application:")
    for app, count in sorted(stats["by_app"].items()):
        print(f"  {app}: {count}")

    print(f"\nBy file type:")
    for ft, count in sorted(stats["by_type"].items()):
        print(f"  {ft}: {count}")

    print(f"\nBy chunk type:")
    for ct, count in sorted(stats["by_chunk_type"].items(), key=lambda x: -x[1]):
        print(f"  {ct}: {count}")


if __name__ == "__main__":
    main()
