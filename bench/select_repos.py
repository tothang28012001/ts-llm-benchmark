"""Stage 2 - deterministic, size-matched selection of the final dataset.

Rule (no hand-picking):
1. LLM group: the N most-starred eligible LLM repositories whose test runner is
   one StrykerJS can drive (vitest / jest / mocha / node --test / ava).
2. Human group: for each selected LLM repository, in descending star order,
   the not-yet-chosen eligible human repository (stars >= 100, same runner
   constraint) whose TypeScript size is closest on a log scale.  This is
   nearest-neighbour size matching, as proposed ("match projects by size
   where feasible").

Output: dataset/repos.csv - the frozen dataset definition used by `run.py`.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUNNERS = {"vitest", "jest", "mocha", "node --test", "ava", "jasmine"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=12, help="repositories per group (10 + spares)")
    args = ap.parse_args()

    d = pd.read_csv(ROOT / "dataset" / "screened.csv")
    d = d[d.eligible & d.test_runner.isin(RUNNERS)]
    llm = d[d.group == "llm"].sort_values(["stars", "commits"], ascending=False).head(args.n)
    pool = d[(d.group == "human") & (d.stars >= 100)].copy()
    chosen = []
    for _, r in llm.iterrows():
        pool["dist"] = (pool.ts_bytes.apply(math.log) - math.log(r.ts_bytes)).abs()
        best = pool.sort_values(["dist", "stars"], ascending=[True, False]).iloc[0]
        chosen.append(best.drop(labels="dist"))
        pool = pool.drop(index=best.name)
    human = pd.DataFrame(chosen)

    out = pd.concat([human, llm])
    out["repo_id"] = [f"{'H' if g == 'human' else 'L'}{i + 1:02d}"
                      for g, i in zip(out.group, list(range(len(human))) + list(range(len(llm))))]
    out["pin"] = out.apply(lambda r: r.pin_commit if r.group == "human" else "HEAD", axis=1)
    cols = ["repo_id", "group", "full_name", "stars", "created_at", "ts_bytes", "commits",
            "ai_commit_share_last100", "ai_agents", "test_runner", "pin", "pin_date"]
    out[cols].to_csv(ROOT / "dataset" / "repos.csv", index=False)
    print(out[cols].to_string(index=False))


if __name__ == "__main__":
    main()
