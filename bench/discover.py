"""Stage 0 - candidate discovery.

Queries the GitHub search API (through the authenticated `gh` CLI) for
TypeScript repositories that are candidates for the two groups:

* human  - created before 2021, last pushed before ChatGPT/Copilot GA, so the
           code we analyse (pinned to a pre-2021 commit) cannot be LLM-written.
* llm    - created 2025 or later and advertising agent-built development
           (Claude Code, Cursor, Codex, ...).  Authorship is *verified* later by
           `authorship.py`, which measures the share of commits that carry an
           AI-agent trailer.

With --by-trailer, LLM candidates are found instead by searching commit
metadata for each agent's own signature (aider, OpenHands, Gemini, Jules,
Codex, Copilot, Cursor, Devin, Windsurf).  This reaches agents and models
that README phrases miss.  Output: dataset/candidates_trailers.csv.

Output: dataset/candidates.csv (one row per unique repository).
"""
from __future__ import annotations

import csv
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dataset" / "candidates.csv"

HUMAN_QUERIES = [
    "language:TypeScript created:2016-01-01..2020-06-30 pushed:<2022-01-01 stars:100..3000 cli",
    "language:TypeScript created:2016-01-01..2020-06-30 pushed:<2022-01-01 stars:100..3000 library",
    "language:TypeScript created:2016-01-01..2020-06-30 pushed:<2022-01-01 stars:100..3000 api",
    "language:TypeScript created:2016-01-01..2020-06-30 pushed:<2022-01-01 stars:100..3000 app",
    "language:TypeScript created:2016-01-01..2020-06-30 pushed:<2022-01-01 stars:100..3000 parser",
]

LLM_QUERIES = [
    '"built with Claude Code" language:TypeScript created:>=2025-01-01',
    '"Claude Code" in:readme language:TypeScript created:>=2025-01-01 stars:>=5',
    '"vibe coded" language:TypeScript created:>=2025-01-01',
    '"built with Cursor" language:TypeScript created:>=2025-01-01',
    '"built with Codex" language:TypeScript created:>=2025-01-01',
    '"written by Claude" language:TypeScript created:>=2025-01-01',
    '"AI-generated" in:readme language:TypeScript created:>=2025-01-01 stars:>=5',
]

FIELDS = ["full_name", "group_hint", "query", "stars", "created_at", "pushed_at",
          "size_kb", "fork", "archived", "default_branch", "description", "html_url"]


def search(query: str, pages: int = 2) -> list[dict]:
    items: list[dict] = []
    for page in range(1, pages + 1):
        proc = subprocess.run(
            ["gh", "api", "-X", "GET", "search/repositories", "-f", f"q={query}",
             "-f", "per_page=100", "-f", f"page={page}", "-f", "sort=stars"],
            capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            print("  search failed:", proc.stderr.strip()[:200])
            break
        batch = json.loads(proc.stdout).get("items", [])
        items.extend(batch)
        time.sleep(4)  # stay well below the 30 req/min search limit
        if len(batch) < 100:
            break
    return items


# --------------------------------------------------------------------------- by commit trailer
# README phrases mostly find Claude Code projects.  Searching commit metadata for each agent's own
# signature finds projects built with other agents, and with them other models (aider names its model).
TRAILER_OUT = ROOT / "dataset" / "candidates_trailers.csv"
TRAILER_QUERIES = {
    "aider": ['"Co-authored-by: aider"'],
    "openhands": ['"openhands@all-hands.dev"'],
    "gemini": ['"Co-authored-by: Gemini"'],
    "jules": ['"google-labs-jules"'],
    "codex": ['"chatgpt-codex-connector"', '"Co-authored-by: Codex"'],
    "copilot": ['"copilot-swe-agent"'],
    "cursor": ['"cursoragent@cursor.com"'],
    "devin": ['"devin-ai-integration"'],
    "windsurf": ['"Co-authored-by: Windsurf"'],
}
WINDOWS = ["2025-01-01..2025-06-30", "2025-07-01..2025-12-31", "2026-01-01..2026-06-30", "2026-07-01..2026-12-31"]
REPO_FRAGMENT = """
  r%(i)d: repository(owner: %(owner)s, name: %(name)s) {
    nameWithOwner stargazerCount createdAt pushedAt diskUsage isFork isArchived url description
    primaryLanguage { name } defaultBranchRef { name }
  }"""


def gh_search(endpoint: str, query: str, page: int) -> dict:
    for attempt in range(4):
        proc = subprocess.run(
            ["gh", "api", "-X", "GET", f"search/{endpoint}", "-f", f"q={query}", "-f", "per_page=100",
             "-f", f"page={page}", "-f", "sort=committer-date"],
            capture_output=True, text=True, encoding="utf-8")
        time.sleep(7)  # search API: 30 requests/min, and commit search trips secondary limits easily
        if proc.returncode == 0:
            return json.loads(proc.stdout)
        if "rate limit" not in (proc.stdout + proc.stderr).lower():
            print("  search failed:", (proc.stderr or proc.stdout).strip()[:200])
            return {}
        print(f"  rate limited, waiting {60 * (attempt + 1)} s")
        time.sleep(60 * (attempt + 1))
    return {}


def repo_meta(names: list[str]) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    for start in range(0, len(names), 50):
        chunk = names[start:start + 50]
        frags = []
        for i, n in enumerate(chunk):
            owner, name = n.split("/", 1)
            frags.append(REPO_FRAGMENT % {"i": i, "owner": json.dumps(owner), "name": json.dumps(name)})
        proc = subprocess.run(["gh", "api", "graphql", "-f", "query=query {" + "".join(frags) + "\n}"],
                              capture_output=True, text=True, encoding="utf-8")
        data = (json.loads(proc.stdout or "{}").get("data") or {}) if proc.stdout else {}
        for i, n in enumerate(chunk):
            if data.get(f"r{i}"):
                meta[n] = data[f"r{i}"]
        time.sleep(1)
    return meta


def discover_by_trailer(pages: int) -> None:
    found: dict[str, str] = {}  # repo -> agent whose signature found it first
    for agent, queries in TRAILER_QUERIES.items():
        before = len(found)
        for q in queries:
            for window in WINDOWS:
                for page in range(1, pages + 1):
                    res = gh_search("commits", f"{q} committer-date:{window}", page)
                    items = res.get("items", [])
                    for it in items:
                        repo = it.get("repository") or {}
                        if repo.get("full_name") and not repo.get("fork"):
                            found.setdefault(repo["full_name"], agent)
                    if len(items) < 100:
                        break
        print(f"[{agent}] {len(found) - before:5d} new repositories")
    meta = repo_meta(sorted(found))
    rows = []
    for name, m in meta.items():
        lang = (m.get("primaryLanguage") or {}).get("name")
        if lang != "TypeScript" or m["isFork"] or m["isArchived"] or m["createdAt"] < "2025-01-01":
            continue
        rows.append({"full_name": m["nameWithOwner"], "group_hint": "llm", "query": f"commit trailer: {found[name]}",
                     "stars": m["stargazerCount"], "created_at": m["createdAt"], "pushed_at": m["pushedAt"],
                     "size_kb": m["diskUsage"], "fork": m["isFork"], "archived": m["isArchived"],
                     "default_branch": (m.get("defaultBranchRef") or {}).get("name", ""),
                     "description": (m.get("description") or "").replace("\n", " ")[:200], "html_url": m["url"]})
    with TRAILER_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: -r["stars"]))
    print(f"{len(found)} repositories signed by an agent, {len(rows)} TypeScript created 2025+ -> "
          f"{TRAILER_OUT.relative_to(ROOT)}")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--by-trailer", action="store_true",
                    help="find LLM candidates by agent commit signatures -> dataset/candidates_trailers.csv")
    ap.add_argument("--pages", type=int, default=3, help="commit-search pages (100 commits) per agent and half-year")
    args = ap.parse_args()
    if args.by_trailer:
        discover_by_trailer(args.pages)
        return
    rows: dict[str, dict] = {}
    for group, queries in (("human", HUMAN_QUERIES), ("llm", LLM_QUERIES)):
        for q in queries:
            found = search(q)
            print(f"[{group}] {len(found):4d}  {q}")
            for it in found:
                name = it["full_name"]
                if name in rows or it["fork"] or it["archived"] and group == "llm":
                    continue
                rows[name] = {
                    "full_name": name, "group_hint": group, "query": q,
                    "stars": it["stargazers_count"], "created_at": it["created_at"],
                    "pushed_at": it["pushed_at"], "size_kb": it["size"],
                    "fork": it["fork"], "archived": it["archived"],
                    "default_branch": it["default_branch"],
                    "description": (it.get("description") or "").replace("\n", " ")[:200],
                    "html_url": it["html_url"],
                }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows.values())
    print(f"wrote {len(rows)} candidates -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
