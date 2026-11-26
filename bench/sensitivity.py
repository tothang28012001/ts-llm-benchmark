"""Sensitivity analyses promised in the milestone report (Sec. VI).

  strict     human vs. only the Claude Code projects whose full history up to the pin is
             >= 90% agent-attributed (a stricter authorship criterion than the >= 50% screening rule)
  popular    human vs. only the Claude Code projects with >= 10 GitHub stars (the agent group is
             far less popular; this checks that the results are not driven by throw-away projects)
  per_file   lint, `any` and compiler-error counts normalised per production file instead of per KLOC
  stars      within the Claude Code group, Spearman correlation of log(1 + stars) with each metric

Each comparison uses the same tests as the primary analysis (two-sided Mann-Whitney U, Cliff's
delta, Holm correction across the metrics of that analysis) and reports whether the direction
agrees with the primary result in results/group_stats.csv.

Output: results/final/sensitivity.csv, results/final/sensitivity_summary.csv
usage:  python -m bench.sensitivity   (after bench.analyze)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from bench.analyze import METRICS, cliffs_delta, magnitude
from bench.final_stats import holm

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
OUT = RES / "final"

STRICT_SHARE = 0.90
POPULAR_STARS = 10
PER_FILE = [("lint_per_kloc", "Lint violations / file", "RQ1"),
            ("lint_problem_per_kloc", "Problem-type violations / file", "RQ1"),
            ("lint_era_neutral_per_kloc", "Era-neutral violations / file", "RQ1"),
            ("any_per_kloc", "Explicit `any` / file", "RQ1"),
            ("tsc_errors_per_kloc", "tsc errors in project files / file", "RQ3")]


def compare(h: pd.DataFrame, l: pd.DataFrame, metrics, analysis: str) -> pd.DataFrame:
    rows = []
    for col, label, rq in metrics:
        a, b = h[col].dropna().astype(float), l[col].dropna().astype(float)
        r = {"analysis": analysis, "rq": rq, "metric": label, "column": col, "n_human": len(a), "n_llm": len(b)}
        if len(a) >= 3 and len(b) >= 3:
            d = cliffs_delta(b, a)
            r.update({"median_human": round(a.median(), 3), "median_llm": round(b.median(), 3),
                      "mwu_p": round(stats.mannwhitneyu(a, b, alternative="two-sided").pvalue, 4),
                      "cliffs_delta": round(d, 3), "effect": magnitude(d)})
        rows.append(r)
    df = pd.DataFrame(rows)
    df["holm_p"] = df.index.map(holm(df["mwu_p"]))
    return df


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    m = pd.read_csv(RES / "metrics.csv")
    primary = pd.read_csv(RES / "group_stats.csv").set_index("column")
    H, L = m[m.group == "human"], m[m.group == "llm"]

    parts = [compare(H, L[L.ai_commit_share >= STRICT_SHARE], METRICS, f"strict (>= {STRICT_SHARE:.0%} agent commits)"),
             compare(H, L[L.stars >= POPULAR_STARS], METRICS, f"popular (>= {POPULAR_STARS} stars)")]

    pf = m.copy()
    for col, _, _ in PER_FILE:
        pf[col] = pf[col] * pf.prod_kloc / pf.prod_files.where(pf.prod_files > 0)
    parts.append(compare(pf[pf.group == "human"], pf[pf.group == "llm"], PER_FILE, "per-file normalisation"))
    res = pd.concat(parts, ignore_index=True)

    def agrees(r):
        if pd.isna(r.get("cliffs_delta")) or r.column not in primary.index:
            return np.nan
        p = primary.loc[r.column, "cliffs_delta_llm_vs_human"]
        return bool(np.sign(r.cliffs_delta) == np.sign(p)) if abs(p) >= 0.147 else np.nan
    res["same_direction_as_primary"] = res.apply(agrees, axis=1)

    rows = []
    ls = np.log1p(L.stars.astype(float))
    for col, label, rq in METRICS:
        y = L[col].astype(float)
        ok = y.notna()
        if ok.sum() >= 8:
            rho, p = stats.spearmanr(ls[ok], y[ok])
            rows.append({"analysis": "stars (within Claude Code)", "rq": rq, "metric": label, "column": col,
                         "n_llm": int(ok.sum()), "spearman_rho": round(float(rho), 3), "mwu_p": round(float(p), 4)})
    st = pd.DataFrame(rows)
    st["holm_p"] = st.index.map(holm(st["mwu_p"]))
    res = pd.concat([res, st], ignore_index=True)
    res.to_csv(OUT / "sensitivity.csv", index=False)

    # one line per analysis: how many of the primary's significant findings survive
    sig_primary = set(primary.index[primary.holm_p < 0.05])
    summ = []
    for name, g in res.groupby("analysis", sort=False):
        g = g.set_index("column")
        if "cliffs_delta" in g and g.cliffs_delta.notna().any():
            kept = [c for c in sig_primary if c in g.index and g.loc[c, "holm_p"] < 0.05
                    and g.loc[c, "same_direction_as_primary"] is True]
            same = [c for c in sig_primary if c in g.index and g.loc[c, "same_direction_as_primary"] is True]
            summ.append({"analysis": name, "n_human": int(g.n_human.max()), "n_llm": int(g.n_llm.max()),
                         "primary_significant_tested": sum(c in g.index for c in sig_primary),
                         "same_direction": len(same), "still_significant": len(kept),
                         "new_significant": int(sum((g.holm_p < 0.05) & ~g.index.isin(sig_primary)))})
        else:
            summ.append({"analysis": name, "n_llm": int(g.n_llm.max()),
                         "significant_correlations": int((g.holm_p < 0.05).sum()),
                         "max_abs_rho": float(g.spearman_rho.abs().max())})
    summ = pd.DataFrame(summ)
    summ.to_csv(OUT / "sensitivity_summary.csv", index=False)
    pd.set_option("display.width", 240)
    print(res.to_string(index=False))
    print(summ.to_string(index=False))


if __name__ == "__main__":
    main()
