"""Stage 1 - automated screening of discovered candidates.

For every candidate in dataset/candidates.csv this pulls, through one batched
GitHub GraphQL query per 15 repositories:

* the root package.json and whether tsconfig.json exists,
* TypeScript byte count (used as a size proxy before cloning),
* the latest 100 commits on the default branch (message + author), from which
  the share of AI-agent-attributed commits is computed,
* for human candidates, the last commit before 2021-01-01 (the pin).

Each repository is then labelled eligible / ineligible with a reason, so the
selection is reproducible and auditable.  Output: dataset/screened.csv
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import time
from pathlib import Path

from bench.authorship import ai_commit_share

ROOT = Path(__file__).resolve().parents[1]
CAND = ROOT / "dataset" / "candidates.csv"
OUT = ROOT / "dataset" / "screened.csv"
HUMAN_CUTOFF = "2021-01-01T00:00:00Z"
TEST_RUNNERS = ("vitest", "jest", "mocha", "ava", "jasmine", "uvu", "tap", "node --test", "bun test")

FRAGMENT = """
  r%(i)d: repository(owner: %(owner)s, name: %(name)s) {
    nameWithOwner stargazerCount isFork isArchived createdAt
    languages(first: 6, orderBy: {field: SIZE, direction: DESC}) { totalSize edges { size node { name } } }
    pkg: object(expression: "HEAD:package.json") { ... on Blob { text } }
    tsconfig: object(expression: "HEAD:tsconfig.json") { ... on Blob { byteSize } }
    defaultBranchRef { target { ... on Commit {
      history(first: 100) { totalCount nodes { messageHeadline message author { name email user { login } } } }
      pin: history(first: 1, until: "%(cutoff)s") { nodes { oid committedDate } }
    } } }
  }"""


def graphql(query: str) -> dict:
    for attempt in range(4):
        proc = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"],
                              capture_output=True, text=True, encoding="utf-8")
        if proc.returncode == 0 or '"data"' in proc.stdout:
            return json.loads(proc.stdout).get("data") or {}
        print("  graphql retry:", proc.stderr.strip()[:160])
        time.sleep(20 * (attempt + 1))
    return {}


def test_runner(pkg: dict) -> str:
    script = (pkg.get("scripts") or {}).get("test", "")
    if not script or "no test specified" in script:
        return ""
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    for runner in TEST_RUNNERS:
        if runner in script or runner.split()[0] in deps:
            return runner
    return "other"


def assess(row: dict, repo: dict | None) -> dict:
    out = {"full_name": row["full_name"], "group": row["group_hint"], "eligible": False, "reason": ""}
    if not repo:
        out["reason"] = "unavailable"
        return out
    langs = {e["node"]["name"]: e["size"] for e in repo["languages"]["edges"]}
    ts_bytes = langs.get("TypeScript", 0)
    total = repo["languages"]["totalSize"] or 1
    target = (repo.get("defaultBranchRef") or {}).get("target") or {}
    hist = target.get("history") or {"totalCount": 0, "nodes": []}
    pin_nodes = (target.get("pin") or {}).get("nodes") or []
    try:
        pkg = json.loads(repo["pkg"]["text"]) if repo.get("pkg") else None
    except (json.JSONDecodeError, TypeError):
        pkg = None
    share, agents = ai_commit_share(hist["nodes"])
    out.update({
        "stars": repo["stargazerCount"], "created_at": repo["createdAt"][:10],
        "ts_bytes": ts_bytes, "ts_share": round(ts_bytes / total, 3),
        "commits": hist["totalCount"], "ai_commit_share_last100": round(share, 3),
        "ai_agents": ";".join(sorted(agents)),
        "has_tsconfig": bool(repo.get("tsconfig")), "test_runner": test_runner(pkg) if pkg else "",
        "pin_commit": pin_nodes[0]["oid"] if pin_nodes else "",
        "pin_date": pin_nodes[0]["committedDate"][:10] if pin_nodes else "",
        "workspaces": bool(pkg and pkg.get("workspaces")),
    })
    reasons = []
    if pkg is None:
        reasons.append("no root package.json")
    if not out["has_tsconfig"]:
        reasons.append("no root tsconfig")
    if not out["test_runner"]:
        reasons.append("no test script")
    if out["workspaces"]:
        reasons.append("monorepo")
    if out["ts_share"] < 0.6:
        reasons.append("TS share < 60%")
    if not 40_000 <= ts_bytes <= 1_500_000:
        reasons.append("TS size outside 40KB-1.5MB")
    if row["group_hint"] == "human":
        if not out["pin_commit"]:
            reasons.append("no pre-2021 commit")
        if share > 0:
            reasons.append("AI trailers present")
    else:
        if out["commits"] < 10:
            reasons.append("< 10 commits")
        if share < 0.5:
            reasons.append("AI-attributed commit share < 50%")
    out["eligible"] = not reasons
    out["reason"] = "; ".join(reasons)
    return out


def main() -> None:
    rows = list(csv.DictReader(CAND.open(encoding="utf-8")))
    results = []
    for start in range(0, len(rows), 15):
        chunk = rows[start:start + 15]
        frags = []
        for i, r in enumerate(chunk):
            owner, name = r["full_name"].split("/", 1)
            frags.append(FRAGMENT % {"i": i, "owner": json.dumps(owner), "name": json.dumps(name),
                                     "cutoff": HUMAN_CUTOFF})
        data = graphql("query {" + "".join(frags) + "\n}")
        for i, r in enumerate(chunk):
            results.append(assess(r, data.get(f"r{i}")))
        ok = sum(x["eligible"] for x in results)
        print(f"screened {len(results):4d}/{len(rows)}  eligible so far: {ok}")
    fields = list(dict.fromkeys(k for r in results for k in r))
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
