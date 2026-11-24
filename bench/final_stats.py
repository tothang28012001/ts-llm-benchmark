"""Final-paper statistics on top of bench.analyze and bench.compare_agents.

The primary comparison (human vs. Claude Code, unpaired Mann-Whitney U with
Cliff's delta and Holm correction) is computed by bench.analyze.  This script adds
the robustness analyses planned in response to the proposal feedback:

  paired      Wilcoxon signed-rank tests over the kind- and size-matched pairs in
              dataset/pairs.csv, with the matched-pairs rank-biserial correlation r
  pooled      human vs. every agent-built project (Claude Code + other agents)
  size        each metric's rank regressed on group and log(production KLOC), so
              the group coefficient is the difference that remains at equal size
  power       the smallest Cliff's delta that a two-sided Mann-Whitney U test at
              alpha = .05 detects with 80% power for the actual group sizes (simulation)

Outputs: results/final/{paired,pooled,size_adjusted}.csv, results/final/power.json
usage: python -m bench.final_stats   (after bench.analyze and bench.compare_agents)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from bench.analyze import METRICS, cliffs_delta, magnitude

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
OUT = RES / "final"


def holm(ps: pd.Series) -> pd.Series:
    ps = ps.dropna().sort_values()
    out, running, k = {}, 0.0, len(ps)
    for i, (idx, p) in enumerate(ps.items()):
        running = max(running, min(1.0, (k - i) * p))
        out[idx] = round(running, 4)
    return pd.Series(out)


def paired(m: pd.DataFrame) -> pd.DataFrame:
    pairs = pd.read_csv(ROOT / "dataset" / "pairs.csv")
    by = m.set_index("repo_id")
    rows = []
    for col, label, rq in METRICS:
        d = []
        for _, p in pairs.iterrows():
            if p.human in by.index and p.llm in by.index:
                h, l = by.at[p.human, col], by.at[p.llm, col]
                if pd.notna(h) and pd.notna(l):
                    d.append(float(l) - float(h))
        d = np.array(d)
        r = {"rq": rq, "metric": label, "column": col, "n_pairs": len(d)}
        nz = d[d != 0]
        if len(nz) >= 6:
            w = stats.wilcoxon(nz)
            ranks = stats.rankdata(np.abs(nz))
            rb = (ranks[nz > 0].sum() - ranks[nz < 0].sum()) / ranks.sum()   # + means LLM higher
            r.update({"median_diff": round(float(np.median(d)), 3), "wilcoxon_p": round(float(w.pvalue), 4),
                      "rank_biserial": round(float(rb), 3), "llm_higher_pairs": int((d > 0).sum())})
        rows.append(r)
    df = pd.DataFrame(rows)
    df["holm_p"] = holm(df.set_index(df.index)["wilcoxon_p"]) if "wilcoxon_p" in df else np.nan
    return df


def pooled(am: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col, label, rq in METRICS:
        h = am.loc[am.stratum == "human", col].dropna().astype(float)
        a = am.loc[am.stratum != "human", col].dropna().astype(float)
        r = {"rq": rq, "metric": label, "column": col, "n_human": len(h), "n_ai": len(a)}
        if len(h) >= 3 and len(a) >= 3:
            dl = cliffs_delta(a, h)
            r.update({"median_human": round(h.median(), 3), "median_ai": round(a.median(), 3),
                      "mwu_p": round(stats.mannwhitneyu(h, a, alternative="two-sided").pvalue, 4),
                      "cliffs_delta_ai_vs_human": round(dl, 3), "effect": magnitude(dl)})
        rows.append(r)
    df = pd.DataFrame(rows)
    df["holm_p"] = holm(df["mwu_p"])
    return df


def size_adjusted(m: pd.DataFrame) -> pd.DataFrame:
    rows = []
    x = m[m.prod_kloc > 0].copy()
    x["log_kloc"] = np.log(x.prod_kloc)
    x["llm"] = (x.group == "llm").astype(float)
    for col, label, rq in METRICS:
        y = x[[col, "llm", "log_kloc"]].dropna()
        if len(y) < 10 or y.llm.nunique() < 2:
            continue
        rk = stats.rankdata(y[col].astype(float)) / len(y)          # rank-transformed outcome (0-1)
        X = np.column_stack([np.ones(len(y)), y.llm.values, y.log_kloc.values])
        beta, *_ = np.linalg.lstsq(X, rk, rcond=None)
        resid = rk - X @ beta
        dof = len(y) - 3
        cov = (resid @ resid / dof) * np.linalg.inv(X.T @ X)
        t = beta[1] / np.sqrt(cov[1, 1])
        rows.append({"rq": rq, "metric": label, "column": col, "n": len(y),
                     "llm_rank_shift": round(float(beta[1]), 3), "size_coef": round(float(beta[2]), 3),
                     "p": round(float(2 * stats.t.sf(abs(t), dof)), 4)})
    df = pd.DataFrame(rows)
    df["holm_p"] = holm(df["p"])
    return df


def power(n1: int, n2: int, reps: int = 2000) -> dict:
    """Smallest Cliff's delta detected with 80% power (normal location shift, alpha .05 two-sided)."""
    rng = np.random.default_rng(479)
    res = {}
    for shift in np.arange(0.2, 1.6, 0.05):
        hits = 0
        for _ in range(reps):
            a, b = rng.normal(0, 1, n1), rng.normal(shift, 1, n2)
            hits += stats.mannwhitneyu(a, b, alternative="two-sided").pvalue < 0.05
        if hits / reps >= 0.8:
            delta = 2 * stats.norm.cdf(shift / np.sqrt(2)) - 1
            res = {"n1": n1, "n2": n2, "cohens_d": round(float(shift), 2), "cliffs_delta": round(float(delta), 2)}
            break
    return res


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    m = pd.read_csv(RES / "metrics.csv")
    am = pd.read_csv(RES / "agents" / "metrics.csv")
    pd.set_option("display.width", 220)
    for name, df in (("paired", paired(m)), ("pooled", pooled(am)), ("size_adjusted", size_adjusted(m))):
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"--- {name}\n{df.to_string(index=False)}")
    nH, nL = int((m.group == "human").sum()), int((m.group == "llm").sum())
    pw = {"primary": power(nH, nL), "milestone_12": power(12, 12),
          "pooled": power(nH, int((am.stratum != "human").sum()))}
    (OUT / "power.json").write_text(json.dumps(pw, indent=2))
    print(pw)


if __name__ == "__main__":
    main()
