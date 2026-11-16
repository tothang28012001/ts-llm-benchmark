"""Records where every lint violation is, for the explorer's code view.

Runs the benchmark's own ESLint pass (tools/lint.mjs, same rules and versions)
on the host over the already-cloned repositories in work/repos, and writes
explorer/cache/<id>/lint-locations.json.  The per-rule counts are checked
against the stored results/raw/<id>/lint.json, so the code view shows exactly
the violations the benchmark counted.  A01... projects are read from
results/raw_agents/.

usage: python -m explorer.prepare [--only H01,L01]
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOS = ROOT / "work" / "repos"
RAW = ROOT / "results" / "raw"
RAW_AGENTS = ROOT / "results" / "raw_agents"
CACHE = ROOT / "explorer" / "cache"


def prepare(rid: str) -> str:
    raw = (RAW_AGENTS if rid.startswith("A") else RAW) / rid
    out = CACHE / rid
    out.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["node", str(ROOT / "tools" / "lint.mjs"), str(raw / "files.json"),
                        str(out / "lint.json"), str(out / "lint-locations.json")],
                       cwd=REPOS / rid, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        return f"failed: {r.stderr.strip()[-300:]}"
    mine = json.loads((out / "lint.json").read_text(encoding="utf-8"))["violations"]
    stored = json.loads((raw / "lint.json").read_text(encoding="utf-8"))["violations"]
    (out / "lint.json").unlink()
    n = len(json.loads((out / "lint-locations.json").read_text(encoding="utf-8")))
    return f"{n} violations, {'matches' if mine == stored else 'DIFFERS FROM'} stored counts"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    for d in sorted([*RAW.iterdir(), *(RAW_AGENTS.iterdir() if RAW_AGENTS.exists() else [])]):
        if (d / "files.json").exists() and (not args.only or d.name in args.only.split(",")):
            print(d.name, prepare(d.name), flush=True)


if __name__ == "__main__":
    main()
