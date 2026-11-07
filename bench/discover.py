"""Stage 0 - candidate discovery.

Queries the GitHub search API (through the authenticated `gh` CLI) for
TypeScript repositories that are candidates for the two groups:

* human  - created before 2021, last pushed before ChatGPT/Copilot GA, so the
           code we analyse (pinned to a pre-2021 commit) cannot be LLM-written.
* llm    - created 2025 or later and advertising agent-built development
           (Claude Code, Cursor, Codex, ...).  Authorship is *verified* later by
           `authorship.py`, which measures the share of commits that carry an
           AI-agent trailer.

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


def main() -> None:
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
