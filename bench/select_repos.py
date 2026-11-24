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

With --agents, builds the "other agents" extension instead: every eligible
project from dataset/screened_trailers.csv (found by agent commit signature)
whose main agent is not Claude Code and whose runner StrykerJS can drive, in
descending star order, numbered A01, A02, ...  It is not size-matched; it is
compared against both existing groups.  Output: dataset/repos_agents.csv
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
    ap.add_argument("--agents", action="store_true", help="build dataset/repos_agents.csv (non-Claude agents)")
    ap.add_argument("--extend", action="store_true",
                    help="grow dataset/repos.csv to every eligible Claude Code project, kind- and size-matched")
    args = ap.parse_args()
    if args.agents:
        select_agents()
        return
    if args.extend:
        extend()
        return

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


def extend() -> None:
    """Final-study extension (instructor feedback: >= 30 projects per group, match by kind and size).

    The 12 milestone pairs (H01-H12 / L01-L12) stay frozen.  Every other eligible
    project whose main agent is Claude Code - from the README route and from the
    commit-signature route - joins the LLM group as L13, L14, ... in descending
    star order.  Each is paired with the not-yet-chosen eligible human project
    (>= 100 stars) that best matches it in kind (dataset/kinds.csv) and
    TypeScript size on a log scale.  The cost is |log size ratio| + ln 2 when the
    kinds differ, so a same-kind project is preferred unless it is more than twice
    as far off in size; dataset/pairs.csv records every pair.  Eligible projects
    built mainly by Codex (README route) join the other-agent group as A21, ...
    Projects whose package.json can no longer be read (deleted or private) are skipped.
    """
    kinds = dict(pd.read_csv(ROOT / "dataset" / "kinds.csv")[["full_name", "kind"]].values)
    cur = pd.read_csv(ROOT / "dataset" / "repos.csv")
    agents = pd.read_csv(ROOT / "dataset" / "repos_agents.csv")
    taken = set(cur.full_name) | set(agents.full_name)

    s = pd.read_csv(ROOT / "dataset" / "screened.csv")
    s = s[s.eligible & s.test_runner.isin(RUNNERS)]
    t = pd.read_csv(ROOT / "dataset" / "screened_trailers.csv")
    t = t[t.eligible & t.test_runner.isin(RUNNERS)]
    readme_llm = s[s.group == "llm"].copy()
    readme_llm["main_agent"] = readme_llm.ai_agents.fillna("").map(
        lambda a: "claude-code" if "claude-code" in a else a.split(";")[0])
    llm = pd.concat([readme_llm, t[t.main_agent == "claude-code"]]).drop_duplicates("full_name")
    llm["kind"] = llm.full_name.map(kinds)
    llm = llm[~llm.full_name.isin(taken) & llm.kind.notna() & (llm.kind != "unknown")]
    codex = llm[llm.main_agent == "codex"]
    llm = llm[llm.main_agent == "claude-code"].sort_values(["stars", "commits"], ascending=False)

    pool = s[(s.group == "human") & (s.stars >= 100) & ~s.full_name.isin(taken)].copy()
    pool["kind"] = pool.full_name.map(kinds)
    pool = pool[pool.kind.notna() & (pool.kind != "unknown")]
    chosen, flags = [], []
    for _, r in llm.iterrows():
        # matching cost: log size distance, plus ln 2 when the kinds differ, so a project of
        # the same kind is preferred unless it is more than twice as far off in size
        pool["dist"] = ((pool.ts_bytes.apply(math.log) - math.log(r.ts_bytes)).abs()
                        + math.log(2) * (pool.kind != r.kind))
        best = pool.sort_values(["dist", "stars"], ascending=[True, False]).iloc[0]
        chosen.append(best.drop(labels="dist"))
        flags.append(best.kind == r.kind)
        pool = pool.drop(index=best.name)
    human = pd.DataFrame(chosen)
    n0 = len(cur) // 2
    human["repo_id"] = [f"H{n0 + i + 1:02d}" for i in range(len(human))]
    llm["repo_id"] = [f"L{n0 + i + 1:02d}" for i in range(len(llm))]
    human["pin"] = human.pin_commit
    llm["pin"], llm["pin_date"] = "HEAD", ""
    llm["group"] = "llm"
    cols = list(cur.columns)
    new = pd.concat([human, llm])
    new[["stars", "ts_bytes", "commits"]] = new[["stars", "ts_bytes", "commits"]].astype(int)
    out = pd.concat([cur, new[cols]])
    out.to_csv(ROOT / "dataset" / "repos.csv", index=False)

    pairs = pd.DataFrame({"human": human.repo_id.values, "llm": llm.repo_id.values,
                          "human_kind": human.kind.values, "llm_kind": llm.kind.values,
                          "same_kind": flags,
                          "size_ratio": (human.ts_bytes.values / llm.ts_bytes.values).round(2)})
    first = pd.DataFrame({"human": cur[cur.group == "human"].repo_id.values,
                          "llm": cur[cur.group == "llm"].repo_id.values})
    first["human_kind"] = cur[cur.group == "human"].full_name.map(kinds).values
    first["llm_kind"] = cur[cur.group == "llm"].full_name.map(kinds).values
    first["same_kind"] = first.human_kind == first.llm_kind
    first["size_ratio"] = (cur[cur.group == "human"].ts_bytes.values / cur[cur.group == "llm"].ts_bytes.values).round(2)
    pd.concat([first, pairs]).to_csv(ROOT / "dataset" / "pairs.csv", index=False)
    print(new[["repo_id", "full_name", "kind", "stars", "ts_bytes"]].to_string(index=False))
    print("same-kind pairs among new:", sum(flags), "/", len(flags))

    if len(codex):
        codex = codex.sort_values(["stars", "commits"], ascending=False).copy()
        codex["repo_id"] = [f"A{len(agents) + i + 1:02d}" for i in range(len(codex))]
        codex["pin"], codex["pin_date"], codex["ai_models"] = "HEAD", "", ""
        codex[["stars", "ts_bytes", "commits"]] = codex[["stars", "ts_bytes", "commits"]].astype(int)
        pd.concat([agents, codex[list(agents.columns)]]).to_csv(ROOT / "dataset" / "repos_agents.csv", index=False)
        print(codex[["repo_id", "full_name", "kind"]].to_string(index=False))


def select_agents() -> None:
    d = pd.read_csv(ROOT / "dataset" / "screened_trailers.csv")
    taken = set(pd.read_csv(ROOT / "dataset" / "repos.csv").full_name)
    d = d[d.eligible & d.test_runner.isin(RUNNERS) & (d.main_agent != "claude-code") & ~d.full_name.isin(taken)]
    out = d.sort_values(["stars", "commits"], ascending=False).copy()
    out["repo_id"] = [f"A{i + 1:02d}" for i in range(len(out))]
    out["pin"], out["pin_date"] = "HEAD", ""
    out[["stars", "ts_bytes", "commits"]] = out[["stars", "ts_bytes", "commits"]].astype(int)
    cols = ["repo_id", "group", "full_name", "stars", "created_at", "ts_bytes", "commits",
            "ai_commit_share_last100", "ai_agents", "main_agent", "ai_models", "test_runner", "pin", "pin_date"]
    out[cols].to_csv(ROOT / "dataset" / "repos_agents.csv", index=False)
    print(out[cols].to_string(index=False))


if __name__ == "__main__":
    main()
