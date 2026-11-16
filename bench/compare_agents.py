"""Three-way comparison: human vs Claude Code vs other coding agents.

The main study (bench.analyze) compares 12 human projects with 12 projects
built mostly by Claude Code.  The extension in dataset/repos_agents.csv adds
projects found by other agents' commit signatures (Cursor, Devin, Copilot,
Jules, OpenHands), run with the same pipeline into results/raw_agents/.

This script measures all three groups with the same metric definitions and
tests the "other agents" group against each existing group (Mann-Whitney U,
Cliff's delta, Holm correction within each comparison).  The main study's
outputs are not touched.

Outputs
  results/agents/metrics.csv        one row per repository, all three groups
  results/agents/group_stats.csv    medians per group, other-vs-human and other-vs-Claude tests
  results/agents/outcomes.csv       install / compile / test / mutation counts per group

Projects listed in dataset/agents_exclusions.csv are left out, with the reason recorded there.
  results/figures/metrics_by_agent_group.png

usage: python -m bench.compare_agents
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from bench.analyze import METRICS, cliffs_delta, magnitude, repo_metrics

ROOT = Path(__file__).resolve().parents[1]
RAW_MAIN = ROOT / "results" / "raw"
RAW_AGENTS = ROOT / "results" / "raw_agents"
OUT = ROOT / "results" / "agents"
FIG = ROOT / "results" / "figures"
GROUPS = ["human", "claude", "other"]
LABELS = {"human": "Human (pre-2021)", "claude": "Claude Code (2025+)", "other": "Other agents (2025+)"}
COLORS = {"human": "#2a78d6", "claude": "#eb6834", "other": "#1baf7a"}   # categorical slots 1-3


EXCLUDED = (lambda f: dict(pd.read_csv(f).values) if f.exists() else {})(ROOT / "dataset" / "agents_exclusions.csv")


def collect() -> pd.DataFrame:
    agent_of = {r["repo_id"]: r.get("main_agent", "") for r in
                csv.DictReader((ROOT / "dataset" / "repos_agents.csv").open(encoding="utf-8"))}
    rows = []
    for raw in (RAW_MAIN, RAW_AGENTS):
        if not raw.exists():
            continue
        for d in sorted(raw.iterdir()):
            if not (d / "summary.json").exists() or d.name in EXCLUDED:
                continue
            try:
                m, _, _ = repo_metrics(d)
            except (KeyError, TypeError):  # stopped before the static stages finished
                continue
            rid = m["repo_id"]
            m["stratum"] = "human" if rid.startswith("H") else "claude" if rid.startswith("L") else "other"
            m["main_agent"] = "" if m["stratum"] == "human" else "claude-code" if m["stratum"] == "claude" else agent_of.get(rid, "")
            rows.append(m)
    return pd.DataFrame(rows)


def compare(df: pd.DataFrame, a: str, b: str) -> list[dict]:
    out = []
    for col, label, rq in METRICS:
        x = df.loc[df.stratum == a, col].dropna().astype(float)
        y = df.loc[df.stratum == b, col].dropna().astype(float)
        r = {"metric": label, "column": col, "comparison": f"{a}_vs_{b}", f"n_{a}": len(x), f"n_{b}": len(y)}
        if len(x) >= 3 and len(y) >= 3:
            d = cliffs_delta(x, y)  # positive = first group higher
            r.update({"mwu_p": round(stats.mannwhitneyu(x, y, alternative="two-sided").pvalue, 4),
                      "cliffs_delta": round(d, 3), "effect": magnitude(d)})
        out.append(r)
    tested = sorted((r for r in out if "mwu_p" in r), key=lambda r: r["mwu_p"])
    running = 0.0
    for i, r in enumerate(tested):
        running = max(running, min(1.0, (len(tested) - i) * r["mwu_p"]))
        r["holm_p"] = round(running, 4)
    return out


def figure(df: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": "#8a8984",
                         "axes.linewidth": 0.6, "xtick.color": "#52514e", "ytick.color": "#52514e",
                         "axes.titlesize": 8.5, "axes.titleweight": "bold"})
    panels = [("lint_per_kloc", "Lint violations / KLOC", "log"),
              ("any_per_kloc", "Explicit any / KLOC", "log"),
              ("cc_mean", "Mean cyclomatic compl.", "linear"),
              ("dup_pct", "Duplicated lines (%)", "linear"),
              ("test_to_code", "Test-to-code ratio", "linear"),
              ("mutation_score", "Mutation score (%)", "linear")]
    fig, axes = plt.subplots(3, 2, figsize=(3.5, 4.6))
    rng = np.random.default_rng(479)
    for ax, (col, title, scale) in zip(axes.flat, panels):
        for i, g in enumerate(GROUPS):
            v = df.loc[df.stratum == g, col].dropna().astype(float).values
            if col == "mutation_score":
                v = 100 * v
            if scale == "log":
                v = np.maximum(v, 0.3)
            ax.scatter(i + rng.uniform(-0.15, 0.15, len(v)), v, s=12, color=COLORS[g], edgecolor="white",
                       linewidth=0.6, zorder=3)
            if len(v):
                ax.hlines(np.median(v), i - 0.3, i + 0.3, color="#0b0b0b", linewidth=1.5, zorder=4)
        ax.set_xticks(range(3), ["Human", "Claude", "Other"])
        ax.set_xlim(-0.6, 2.6)
        ax.set_title(title, loc="left", fontsize=7.5)
        ax.tick_params(labelsize=6.5, length=2)
        ax.grid(axis="y", color="#e4e3df", linewidth=0.5)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        if scale == "log":
            ax.set_yscale("log")
            ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{y:g}"))
    fig.tight_layout(pad=0.4, w_pad=0.6, h_pad=0.8)
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / "metrics_by_agent_group.png", dpi=300)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = collect()
    df.to_csv(OUT / "metrics.csv", index=False)

    med = []
    for col, label, rq in METRICS:
        row = {"rq": rq, "metric": label, "column": col}
        for g in GROUPS:
            v = df.loc[df.stratum == g, col].dropna().astype(float)
            row[f"n_{g}"], row[f"median_{g}"] = len(v), round(v.median(), 3) if len(v) else np.nan
        med.append(row)
    gs = pd.DataFrame(med)
    for a, b in (("other", "human"), ("other", "claude")):
        c = pd.DataFrame(compare(df, a, b)).set_index("column")
        for k in ("mwu_p", "holm_p", "cliffs_delta", "effect"):
            gs[f"{k}_{a}_vs_{b}"] = gs.column.map(c[k]) if k in c else np.nan
    gs.to_csv(OUT / "group_stats.csv", index=False)

    oc = []
    for g in GROUPS:
        x = df[df.stratum == g]
        mut_ok = x.mutation_score.notna()
        oc.append({"group": g, "n": len(x), "install_ok": int(x.install_ok.fillna(False).astype(bool).sum()),
                   "tsc_clean": int(x.tsc_clean.fillna(False).astype(bool).sum()),
                   "tests_passed": int(x.tests_passed.fillna(False).astype(bool).sum()),
                   "mutation_valid": int(mut_ok.sum())})
    pd.DataFrame(oc).to_csv(OUT / "outcomes.csv", index=False)
    figure(df)

    pd.set_option("display.width", 240)
    print(df[df.stratum == "other"][["repo_id", "main_agent", "full_name", "prod_kloc", "lint_per_kloc", "cc_mean",
                                     "dup_pct", "install_ok", "tsc_clean", "tests_passed", "mutation_score"]].to_string(index=False))
    cols = ["metric"] + [f"median_{g}" for g in GROUPS] + ["holm_p_other_vs_human", "cliffs_delta_other_vs_human",
                                                          "holm_p_other_vs_claude", "cliffs_delta_other_vs_claude"]
    print(gs[cols].to_string(index=False))
    print(pd.DataFrame(oc).to_string(index=False))


if __name__ == "__main__":
    main()
