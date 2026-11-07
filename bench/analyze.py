"""Aggregate per-repository results into metrics, group statistics and figures.

Outputs
  results/metrics.csv          one row per repository, every derived metric
  results/group_stats.csv      medians per group, Mann-Whitney U p-value, Cliff's delta
  results/top_rules.csv        most frequent ESLint/SonarJS rules per group (per KLOC)
  results/tsc_codes.csv        TypeScript diagnostic codes per group
  results/figures/*.png        figures used in the report

usage: python -m bench.analyze
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
import os
RAW = Path(os.environ.get("BENCH_RAW", ROOT / "results" / "raw"))
RES = Path(os.environ.get("BENCH_RES", ROOT / "results"))
FIG = RES / "figures"
COLORS = {"human": "#2a78d6", "llm": "#eb6834"}     # categorical slots 1-2 (validated palette)
# Rules that mostly encode language/tooling *era* rather than code quality: they flag idioms
# that were idiomatic or unavoidable before TypeScript 3.x / ES2015 module adoption
# (`any` before `unknown` (TS 3.0), `var`, `require`, `namespace`, wrapper object types).
ERA_RULES = {"@typescript-eslint/no-explicit-any", "no-var", "prefer-const", "@typescript-eslint/no-require-imports",
             "@typescript-eslint/no-wrapper-object-types", "@typescript-eslint/no-unsafe-function-type",
             "@typescript-eslint/no-empty-object-type", "sonarjs/no-primitive-wrappers", "@typescript-eslint/no-namespace",
             "@typescript-eslint/triple-slash-reference", "@typescript-eslint/no-this-alias", "@typescript-eslint/ban-ts-comment"}
LABELS = {"human": "Human (pre-2021)", "llm": "LLM agent (2025+)"}


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


ANSI = re.compile(r"\[[0-9;]*m")


def test_counts(log: Path) -> tuple[int | None, int | None]:
    """(passed, failed) from jest / vitest / mocha / node:test / ava output, or (None, None)."""
    if not log.exists():
        return None, None
    t = ANSI.sub("", log.read_text(encoding="utf-8", errors="replace"))
    m = re.findall(r"^\s*Tests:\s+(.*)$", t, re.M)                       # jest: Tests: 4 failed, 233 passed, 237 total
    if m:
        last = m[-1]
        f = re.search(r"(\d+) failed", last); ps = re.search(r"(\d+) passed", last)
        return int(ps.group(1)) if ps else 0, int(f.group(1)) if f else 0
    m = re.findall(r"^\s*Tests\s+(.*)$", t, re.M)                        # vitest: Tests  2 failed | 42 passed (44)
    if m:
        last = m[-1]
        f = re.search(r"(\d+) failed", last); ps = re.search(r"(\d+) passed", last)
        return int(ps.group(1)) if ps else 0, int(f.group(1)) if f else 0
    ps = re.findall(r"^# pass (\d+)", t, re.M); f = re.findall(r"^# fail (\d+)", t, re.M)   # node:test / tap
    if ps:
        return int(ps[-1]), int(f[-1]) if f else 0
    ps = re.findall(r"(\d+) passing", t); f = re.findall(r"(\d+) failing", t)                # mocha
    if ps:
        return int(ps[-1]), int(f[-1]) if f else 0
    ps = re.findall(r"(\d+) tests? passed", t); f = re.findall(r"(\d+) tests? failed", t)    # ava
    if ps or f:
        return int(ps[-1]) if ps else 0, int(f[-1]) if f else 0
    return None, None


EXCLUDED = (lambda f: dict(pd.read_csv(f).values) if f.exists() else {})(ROOT / "dataset" / "mutation_exclusions.csv")


def _mut_valid(mut: dict) -> bool:
    c, v = mut.get("counts") or {}, mut.get("mutants_valid") or 0
    return mut.get("status") == "ok" and v > 0 and c.get("Timeout", 0) / v <= 0.5


def repo_metrics(d: Path) -> tuple[dict, dict, dict]:
    s = load(d / "summary.json")
    lint = load(d / "lint.json")
    dup = load(d / "jscpd" / "jscpd-report.json")
    loc = s.get("loc", {})
    prod, test = loc.get("prod", {}), loc.get("test", {})
    kloc = max(prod.get("code", 0), 1) / 1000
    viol = lint.get("violations", {}).get("prod", {})
    types = lint.get("rule_type", {})
    cc = np.array(lint.get("cyclomatic", []) or [np.nan])
    nfun = max(lint.get("functions_prod", 0), 1)
    cog = np.array(lint.get("cognitive", []) or [0])
    tsc = s.get("tsc", {})
    total = dup.get("statistics", {}).get("total", {})
    mut = s.get("mutation", {})
    if s["repo_id"] in EXCLUDED and mut.get("status") == "ok":
        mut = {**mut, "status": "excluded"}
    m = {
        "repo_id": s["repo_id"], "group": s["group"], "full_name": s["full_name"],
        "stars": int(s["stars"]), "pin_date": s["fetch"]["commit_date"][:10],
        "ai_commit_share": s["fetch"]["ai_commit_share"], "commits_to_pin": s["fetch"]["commits_to_pin"],
        "prod_files": prod.get("files", 0), "prod_kloc": round(prod.get("code", 0) / 1000, 2),
        "test_kloc": round(test.get("code", 0) / 1000, 2),
        "test_to_code": round(test.get("code", 0) / max(prod.get("code", 0), 1), 3),
        "has_tests": test.get("files", 0) > 0,
        "comment_density": round(prod.get("comment", 0) / max(prod.get("comment", 0) + prod.get("code", 0), 1), 4),
        "lint_per_kloc": round(sum(viol.values()) / kloc, 2),
        "lint_problem_per_kloc": round(sum(v for r, v in viol.items() if types.get(r) == "problem") / kloc, 2),
        "lint_suggestion_per_kloc": round(sum(v for r, v in viol.items() if types.get(r) != "problem") / kloc, 2),
        "lint_era_neutral_per_kloc": round(sum(v for r, v in viol.items() if r not in ERA_RULES) / kloc, 2),
        "lint_era_neutral_problem_per_kloc": round(sum(v for r, v in viol.items() if r not in ERA_RULES and types.get(r) == "problem") / kloc, 2),
        "any_per_kloc": round(viol.get("@typescript-eslint/no-explicit-any", 0) / kloc, 2),
        "functions_per_kloc": round(lint.get("functions_prod", 0) / kloc, 1),
        "cc_mean": round(float(np.nanmean(cc)), 3), "cc_p90": float(np.nanpercentile(cc, 90)),
        "cc_over10_pct": round(100 * float(np.nansum(cc > 10)) / nfun, 2),
        "cognitive_mean": round(float(cog.sum()) / nfun, 3),
        "cognitive_over15_pct": round(100 * float((cog > 15).sum()) / nfun, 2),
        "dup_pct": round(float(total.get("percentage", np.nan)), 2), "dup_clones": total.get("clones", np.nan),
        "install_ok": s.get("install", {}).get("ok"), "install_level": s.get("install", {}).get("level"),
        "ts_version": tsc.get("ts_version"), "tsc_clean": tsc.get("errors_total", 1) == 0,
        "tsc_project_clean": (tsc.get("errors_in_project_files", 1) == 0 and tsc.get("global_errors", 1) == 0) if tsc else None,
        "tsc_errors_deps": tsc.get("errors_in_dependencies"),
        "tsc_errors": tsc.get("errors_total"), "tsc_errors_project": tsc.get("errors_in_project_files"),
        "tsc_errors_per_kloc": round(tsc.get("errors_in_project_files", 0) / kloc, 2) if tsc else np.nan,
        "tsc_files_with_errors_pct": round(100 * tsc.get("files_with_errors", 0) / max(prod.get("files", 0) + test.get("files", 0), 1), 2) if tsc else np.nan,
        "tests_passed": s.get("test", {}).get("passed"),
        "tests_n_passed": test_counts(d / "test.log")[0], "tests_n_failed": test_counts(d / "test.log")[1],
        # suites that could not run at all (install failure, crash before any test) count as 0% passing
        "test_pass_rate": (lambda pf: round(pf[0] / (pf[0] + pf[1]), 4) if pf[0] is not None and (pf[0] + pf[1])
                           else (np.nan if s.get("test", {}).get("passed") else 0.0))(test_counts(d / "test.log")),
        "tests_passed_legacy": (s.get("test_legacy") or {}).get("passed"),
        "legacy_node": (s.get("test_legacy") or {}).get("node"),
        # a run where most mutants only "time out" measures machine load, not tests: treat as invalid
        "mutation_timeout_share": round((mut.get("counts") or {}).get("Timeout", 0) / mut["mutants_valid"], 3) if mut.get("mutants_valid") else np.nan,
        "mutation_score": mut.get("mutation_score") if _mut_valid(mut) else np.nan,
        "mutation_score_covered": mut.get("mutation_score_covered") if _mut_valid(mut) else np.nan,
        "mutants": mut.get("mutants_valid"), "mutation_runner": mut.get("runner"),
        "mutation_status": mut.get("status", "not-run") if _mut_valid(mut) or mut.get("status") != "ok" else "invalid-timeouts",
    }
    return m, viol, tsc.get("by_code", {})


def cliffs_delta(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    gt = sum((x > b).sum() for x in a)
    lt = sum((x < b).sum() for x in a)
    return (gt - lt) / (len(a) * len(b))


def magnitude(d: float) -> str:
    d = abs(d)
    return "negligible" if d < 0.147 else "small" if d < 0.33 else "medium" if d < 0.474 else "large"


METRICS = [  # (column, label, research question)
    ("lint_per_kloc", "Lint violations / KLOC", "RQ1"),
    ("lint_problem_per_kloc", "Problem-type violations / KLOC", "RQ1"),
    ("lint_suggestion_per_kloc", "Suggestion-type violations / KLOC", "RQ1"),
    ("lint_era_neutral_per_kloc", "Era-neutral violations / KLOC", "RQ1"),
    ("lint_era_neutral_problem_per_kloc", "Era-neutral problem violations / KLOC", "RQ1"),
    ("any_per_kloc", "Explicit `any` / KLOC", "RQ1"),
    ("functions_per_kloc", "Functions / KLOC", "RQ2"),
    ("cc_mean", "Mean cyclomatic complexity / function", "RQ2"),
    ("cc_over10_pct", "% functions with CC > 10", "RQ2"),
    ("cognitive_mean", "Mean cognitive complexity / function", "RQ2"),
    ("cognitive_over15_pct", "% functions with cognitive > 15", "RQ2"),
    ("dup_pct", "Duplicated lines (%)", "RQ2"),
    ("comment_density", "Comment density", "RQ2"),
    ("test_to_code", "Test-to-code LOC ratio", "RQ2"),
    ("tsc_errors_per_kloc", "tsc errors in project files / KLOC", "RQ3"),
    ("test_pass_rate", "Test pass rate (Node 22)", "RQ2"),
    ("mutation_score", "Mutation score", "RQ2"),
    ("mutation_score_covered", "Mutation score, covered code", "RQ2"),
]


def figures(df: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": "#8a8984",
                         "axes.linewidth": 0.6, "xtick.color": "#52514e", "ytick.color": "#52514e",
                         "axes.labelcolor": "#52514e", "axes.titlesize": 8.5, "axes.titleweight": "bold"})
    FIG.mkdir(parents=True, exist_ok=True)
    panels = [("lint_per_kloc", "Lint violations / KLOC", "log"),
              ("lint_problem_per_kloc", "Problems / KLOC", "log"),
              ("cc_mean", "Mean cyclomatic compl.", "linear"),
              ("cc_over10_pct", "Functions CC > 10 (%)", "linear"),
              ("dup_pct", "Duplicated lines (%)", "linear"),
              ("test_pass_rate", "Test pass rate (%)", "pct")]
    fig, axes = plt.subplots(3, 2, figsize=(3.5, 4.3))
    rng = np.random.default_rng(479)
    for ax, (col, title, scale) in zip(axes.flat, panels):
        for i, g in enumerate(["human", "llm"]):
            v = df.loc[df.group == g, col].dropna().astype(float).values
            if scale == "pct":
                v = 100 * v
            if scale == "log":
                v = np.maximum(v, 0.3)  # place zeros on the axis floor
            x = i + rng.uniform(-0.14, 0.14, len(v))
            ax.scatter(x, v, s=14, color=COLORS[g], edgecolor="white", linewidth=0.7, zorder=3)
            if len(v):
                ax.hlines(np.median(v), i - 0.3, i + 0.3, color="#0b0b0b", linewidth=1.6, zorder=4)
        ax.set_xticks([0, 1], ["Human", "LLM"])
        ax.set_xlim(-0.6, 1.6)
        ax.set_title(title, loc="left", fontsize=7.5)
        ax.tick_params(labelsize=6.5, length=2)
        ax.grid(axis="y", color="#e4e3df", linewidth=0.5)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        if scale == "log":
            ax.set_yscale("log")
            ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{y:g}"))
        if scale == "pct":
            ax.set_ylim(-5, 105)
    fig.tight_layout(pad=0.4, w_pad=0.6, h_pad=0.8)
    fig.savefig(FIG / "metrics_by_group.png", dpi=300)
    plt.close(fig)

    # size and authorship overview
    fig, ax = plt.subplots(figsize=(3.5, 2.3))
    for g in ["human", "llm"]:
        x = df[df.group == g]
        ax.scatter(x.prod_kloc, x.lint_per_kloc, s=20, color=COLORS[g], edgecolor="white", linewidth=0.8, label=LABELS[g], zorder=3)
    ax.set_xscale("log")
    ax.set_xlabel("Production code (KLOC, log scale)")
    ax.set_ylabel("Lint violations / KLOC")
    ax.grid(color="#e4e3df", linewidth=0.5)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.legend(frameon=False, fontsize=7, loc="upper left")
    fig.tight_layout(pad=0.4)
    fig.savefig(FIG / "size_vs_lint.png", dpi=300)
    plt.close(fig)


def main() -> None:
    rows, viol_rows, code_rows = [], [], []
    for d in sorted(RAW.iterdir()):
        if not (d / "summary.json").exists() or "loc" not in load(d / "summary.json"):
            continue
        m, viol, codes = repo_metrics(d)
        rows.append(m)
        kloc = max(m["prod_kloc"], 0.001)
        viol_rows += [{"group": m["group"], "repo_id": m["repo_id"], "rule": r, "count": c, "per_kloc": c / kloc} for r, c in viol.items()]
        code_rows += [{"group": m["group"], "repo_id": m["repo_id"], "code": c, "count": n} for c, n in codes.items()]
    df = pd.DataFrame(rows)
    df.to_csv(RES / "metrics.csv", index=False)

    out = []
    for col, label, rq in METRICS:
        h = df.loc[df.group == "human", col].dropna().astype(float)
        l = df.loc[df.group == "llm", col].dropna().astype(float)
        if len(h) < 3 or len(l) < 3:
            out.append({"rq": rq, "metric": label, "column": col, "n_human": len(h), "n_llm": len(l)})
            continue
        p = stats.mannwhitneyu(h, l, alternative="two-sided").pvalue
        d = cliffs_delta(l, h)  # positive = LLM higher
        out.append({"rq": rq, "metric": label, "column": col, "n_human": len(h), "n_llm": len(l),
                    "median_human": round(h.median(), 3), "median_llm": round(l.median(), 3),
                    "iqr_human": f"{h.quantile(.25):.2f}-{h.quantile(.75):.2f}",
                    "iqr_llm": f"{l.quantile(.25):.2f}-{l.quantile(.75):.2f}",
                    "mwu_p": round(p, 4), "cliffs_delta_llm_vs_human": round(d, 3), "effect": magnitude(d)})
    gs = pd.DataFrame(out)
    if "mwu_p" not in gs.columns:
        gs["mwu_p"] = np.nan
    # Holm-Bonferroni correction across the tested metrics
    tested = gs.dropna(subset=["mwu_p"]).sort_values("mwu_p")
    k = len(tested)
    adj, running = {}, 0.0
    for i, (idx, r) in enumerate(tested.iterrows()):
        running = max(running, min(1.0, (k - i) * r.mwu_p))
        adj[idx] = round(running, 4)
    gs["holm_p"] = pd.Series(adj)
    gs.to_csv(RES / "group_stats.csv", index=False)

    # compilation: proportion of repositories that type-check cleanly (Fisher exact)
    ct = pd.crosstab(df.group, df.tsc_clean).reindex(columns=[True, False], fill_value=0)
    fisher_p = stats.fisher_exact(ct.values)[1] if ct.shape == (2, 2) else np.nan
    (RES / "tsc_clean.json").write_text(json.dumps({"table": ct.to_dict(), "fisher_p": round(float(fisher_p), 4)}, indent=2))

    vr = pd.DataFrame(viol_rows)
    if len(vr):
        top = (vr.groupby(["group", "rule"]).agg(repos=("repo_id", "nunique"), total=("count", "sum"),
                                                 median_per_kloc=("per_kloc", "median"))
                 .reset_index().sort_values(["group", "total"], ascending=[True, False]))
        top.groupby("group").head(12).to_csv(RES / "top_rules.csv", index=False)
    cr = pd.DataFrame(code_rows)
    if len(cr):
        cr.groupby(["group", "code"]).agg(repos=("repo_id", "nunique"), total=("count", "sum")).reset_index() \
          .sort_values(["group", "total"], ascending=[True, False]).to_csv(RES / "tsc_codes.csv", index=False)
    figures(df)
    pd.set_option("display.width", 220)
    print(df[["repo_id", "full_name", "prod_kloc", "lint_per_kloc", "cc_mean", "dup_pct", "comment_density",
              "test_to_code", "install_ok", "tsc_errors", "tsc_errors_project"]].to_string(index=False))
    print(gs.to_string(index=False))
    print("tsc clean:", ct.to_dict(), "fisher p =", fisher_p)


if __name__ == "__main__":
    main()
