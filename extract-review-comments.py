#!/usr/bin/env python3
"""Extract GitHub PR review comments from specified reviewers for vector DB ingestion.

Environment variables:
    GITHUB_REPO           - GitHub repo (e.g., "owner/repo") — required
    REVIEW_AUTHORS        - Comma-separated GitHub usernames to include (default: all humans)
    REVIEW_COMMENTS_OUTPUT - Output JSONL path (default: data/review-comments.jsonl)
    TICKET_PATTERN        - Regex to extract ticket IDs from PR titles (default: "[A-Z]+-\\d+")
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict

REPO = os.environ.get("GITHUB_REPO", "")
if not REPO:
    # Auto-detect from git remote
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True, text=True, check=True
        )
        REPO = result.stdout.strip()
    except Exception:
        print("Error: Set GITHUB_REPO env var or run from a git repo with gh CLI.")
        sys.exit(1)

_authors_env = os.environ.get("REVIEW_AUTHORS", "")
FILTER_AUTHORS = set(a.strip() for a in _authors_env.split(",") if a.strip()) if _authors_env else None
OUTPUT_FILE = os.environ.get("REVIEW_COMMENTS_OUTPUT", "data/review-comments.jsonl")
TICKET_PATTERN = re.compile(os.environ.get("TICKET_PATTERN", r"[A-Z]+-\d+"))


def get_gh_token():
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def api_get(url, token, retries=3):
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
                link_header = resp.getheader("Link", "")
            next_url = None
            if 'rel="next"' in link_header:
                for part in link_header.split(","):
                    if 'rel="next"' in part:
                        next_url = part.split("<")[1].split(">")[0]
                        break
            return data, next_url
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"  HTTP {e.code}, retrying in {wait}s (attempt {attempt + 1}/{retries})...")
                time.sleep(wait)
                continue
            raise


def paginate(url, token, label=""):
    all_items = []
    page = 1
    while url:
        try:
            items, url = api_get(url, token)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"  Rate limited, waiting 60s...")
                time.sleep(60)
                continue
            raise
        all_items.extend(items)
        print(f"  {label} page {page}: {len(items)} items (total: {len(all_items)})")
        page += 1
    return all_items


def extract_ticket(title, branch=""):
    for source in [title, branch]:
        match = TICKET_PATTERN.search(source or "")
        if match:
            return match.group(0).upper()
    return None


def extract_pr_number_from_url(pull_request_url):
    # e.g. https://api.github.com/repos/owner/repo/pulls/731
    return int(pull_request_url.rstrip("/").split("/")[-1])


def main():
    token = get_gh_token()
    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    print(f"Authenticated. Fetching data from {REPO}...\n")

    # Step 1: Fetch all PR metadata
    print("Step 1: Fetching PR metadata...")
    prs = paginate(
        f"https://api.github.com/repos/{REPO}/pulls?state=all&per_page=100",
        token, "PRs"
    )
    pr_map = {}
    for pr in prs:
        pr_map[pr["number"]] = {
            "title": pr["title"],
            "branch": pr.get("head", {}).get("ref", ""),
            "url": pr["html_url"],
        }
    print(f"  Total PRs: {len(pr_map)}\n")

    # Step 2: Fetch all inline review comments
    print("Step 2: Fetching inline review comments...")
    all_comments = paginate(
        f"https://api.github.com/repos/{REPO}/pulls/comments?per_page=100",
        token, "Comments"
    )
    print(f"  Total review comments: {len(all_comments)}")

    # Filter to admin users
    def is_human(login):
    return not login.endswith("[bot]")

def is_included(login):
    if FILTER_AUTHORS:
        return login in FILTER_AUTHORS
    return is_human(login)

admin_comments = [c for c in all_comments if is_included(c["user"]["login"])]
    print(f"  Admin comments: {len(admin_comments)}\n")

    # Step 3: Determine which PRs had admin comments, fetch PR-level reviews
    pr_numbers_with_admin_comments = set()
    for c in admin_comments:
        pr_num = extract_pr_number_from_url(c["pull_request_url"])
        pr_numbers_with_admin_comments.add(pr_num)

    print(f"Step 3: Fetching PR-level reviews for {len(pr_numbers_with_admin_comments)} PRs...")
    pr_level_reviews = []
    for i, pr_num in enumerate(sorted(pr_numbers_with_admin_comments), 1):
        try:
            reviews, _ = api_get(
                f"https://api.github.com/repos/{REPO}/pulls/{pr_num}/reviews?per_page=100",
                token
            )
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            if e.code == 403:
                print(f"  Rate limited at PR #{pr_num}, waiting 60s...")
                time.sleep(60)
                reviews, _ = api_get(
                    f"https://api.github.com/repos/{REPO}/pulls/{pr_num}/reviews?per_page=100",
                    token
                )
            else:
                raise
        admin_reviews = [
            r for r in reviews
            if is_included(r["user"]["login"]) and r.get("body", "").strip()
        ]
        pr_level_reviews.extend([(pr_num, r) for r in admin_reviews])
        if i % 20 == 0:
            print(f"  Processed {i}/{len(pr_numbers_with_admin_comments)} PRs...")

    print(f"  PR-level reviews with body text: {len(pr_level_reviews)}\n")

    # Step 4: Write JSONL
    print(f"Step 4: Writing {OUTPUT_FILE}...")
    stats = {"total": 0, "by_reviewer": defaultdict(int), "by_ticket": defaultdict(int)}

    with open(OUTPUT_FILE, "w") as f:
        # Inline comments
        for c in admin_comments:
            pr_num = extract_pr_number_from_url(c["pull_request_url"])
            pr_info = pr_map.get(pr_num, {"title": "", "branch": "", "url": ""})
            ticket = extract_ticket(pr_info["title"], pr_info["branch"])
            reviewer = c["user"]["login"]

            record = {
                "id": c["id"],
                "type": "inline_comment",
                "pr_number": pr_num,
                "pr_title": pr_info["title"],
                "pr_url": pr_info["url"],
                "ticket": ticket,
                "reviewer": reviewer,
                "file_path": c.get("path"),
                "original_line": c.get("original_line"),
                "start_line": c.get("original_start_line"),
                "diff_hunk": c.get("diff_hunk"),
                "body": c["body"],
                "created_at": c["created_at"],
                "updated_at": c["updated_at"],
                "comment_url": c["html_url"],
                "in_reply_to_id": c.get("in_reply_to_id"),
            }
            f.write(json.dumps(record) + "\n")
            stats["total"] += 1
            stats["by_reviewer"][reviewer] += 1
            stats["by_ticket"][ticket or "NO_TICKET"] += 1

        # PR-level review bodies
        for pr_num, review in pr_level_reviews:
            pr_info = pr_map.get(pr_num, {"title": "", "branch": "", "url": ""})
            ticket = extract_ticket(pr_info["title"], pr_info["branch"])
            reviewer = review["user"]["login"]

            record = {
                "id": review["id"],
                "type": "review_body",
                "pr_number": pr_num,
                "pr_title": pr_info["title"],
                "pr_url": pr_info["url"],
                "ticket": ticket,
                "reviewer": reviewer,
                "file_path": None,
                "original_line": None,
                "start_line": None,
                "diff_hunk": None,
                "body": review["body"],
                "state": review.get("state"),
                "created_at": review.get("submitted_at", review.get("created_at")),
                "updated_at": None,
                "comment_url": review["html_url"],
                "in_reply_to_id": None,
            }
            f.write(json.dumps(record) + "\n")
            stats["total"] += 1
            stats["by_reviewer"][reviewer] += 1
            stats["by_ticket"][ticket or "NO_TICKET"] += 1

    # Print summary
    print(f"\nDone! Wrote {stats['total']} records to {OUTPUT_FILE}\n")

    print("By reviewer:")
    for reviewer, count in sorted(stats["by_reviewer"].items(), key=lambda x: -x[1]):
        print(f"  {reviewer}: {count}")

    print(f"\nBy ticket ({len(stats['by_ticket'])} unique):")
    for ticket, count in sorted(stats["by_ticket"].items(), key=lambda x: -x[1])[:20]:
        print(f"  {ticket}: {count}")
    if len(stats["by_ticket"]) > 20:
        print(f"  ... and {len(stats['by_ticket']) - 20} more tickets")


if __name__ == "__main__":
    main()
