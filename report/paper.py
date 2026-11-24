"""Final paper (CMPT 479, Dec. 7): 4 pages + references, IEEE conference format.

Every number is computed from results/ and dataset/ at build time.

Outputs
  report/CMPT479 - Final Paper.pdf
  report/paper.tex     (same content, \\documentclass[10pt,conference]{IEEEtran})

usage: python -m report.paper   (after bench.analyze, bench.compare_agents, bench.final_stats)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

from report.build_report import OUT_DIR, RES, Out, fmt, pval

ROOT = RES.parent
PDF = "CMPT479 - Final Paper.pdf"

REFS = [
    "T. Tang, S. Alimadadi, and N. Sumner, “From logic to toolchains: An empirical study of bugs in the TypeScript ecosystem,” in *Proc. 23rd Int. Conf. Mining Software Repositories (MSR)*, ACM, 2026, pp. 539–549.",
    "A. S. Molison, M. Moraes, G. Melo, F. Santos, and W. K. G. Assunção, “Is LLM-generated code more maintainable & reliable than human-written code?” in *Proc. ACM/IEEE Int. Symp. Empirical Software Engineering and Measurement (ESEM)*, 2025, pp. 151–162.",
    "S. A. Licorish, A. Bajpai, C. Arora, F. Wang, and K. Tantithamthavorn, “Comparing human and LLM generated code: The jury is still out!” arXiv:2501.16857, 2025.",
    "D. Cotroneo, C. Improta, and P. Liguori, “Human-written vs. AI-generated code: A large-scale study of defects, vulnerabilities, and complexity,” in *Proc. 36th IEEE Int. Symp. Software Reliability Engineering (ISSRE)*, 2025, pp. 252–263.",
    "M. Schäfer, S. Nadi, A. Eghbali, and F. Tip, “An empirical evaluation of using large language models for automated unit test generation,” *IEEE Trans. Software Engineering*, vol. 50, no. 1, pp. 85–105, 2024.",
    "F. Tip, J. Bell, and M. Schäfer, “LLMorpheus: Mutation testing using large language models,” *IEEE Trans. Software Engineering*, vol. 51, no. 6, pp. 1645–1665, 2025.",
    "A. Romazanov, G. Fraser, and S. Herbold, “CDBench: Benchmarking the mutation testing capabilities of LLMs with Code Defenders,” *Empirical Software Engineering*, vol. 31, no. 6, art. 166, 2026.",
    "S. Garg, B. Steenhoek, and Y. Huang, “Saving SWE-Bench: A benchmark mutation approach for realistic agent evaluation,” in *Proc. 5th IEEE/ACM Int. Conf. AI Engineering – Software Engineering for AI (CAIN)*, 2026.",
    "M. Bruntink and A. van Deursen, “An empirical study into class testability,” *J. Systems and Software*, vol. 79, no. 9, pp. 1219–1232, 2006.",
    "T. J. McCabe, “A complexity measure,” *IEEE Trans. Software Engineering*, vol. SE-2, no. 4, pp. 308–320, 1976.",
    "G. A. Campbell, “Cognitive complexity: An overview and evaluation,” in *Proc. Int. Conf. Technical Debt (TechDebt)*, 2018, pp. 57–58.",
    "J. Romano, J. D. Kromrey, J. Coraggio, and J. Skowronek, “Appropriate statistics for ordinal level data,” in *Proc. Annual Meeting of the Florida Association of Institutional Research*, 2006.",
    "S. Holm, “A simple sequentially rejective multiple test procedure,” *Scandinavian J. Statistics*, vol. 6, no. 2, pp. 65–70, 1979.",
    "StrykerJS, https://stryker-mutator.io; ESLint, https://eslint.org; typescript-eslint, https://typescript-eslint.io; SonarJS, https://github.com/SonarSource/SonarJS; jscpd, https://github.com/kucherenko/jscpd.",
]


def words(n: int) -> str:
    w = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
    return w[n] if 0 <= n <= 10 else str(n)


def peq(p) -> str:
    """'~=~0.012' or '~<~0.001', to follow an italic *p*."""
    v = pval(p)
    return "~<~0.001" if v == "<0.001" else f"~=~{v}"


def sig(p) -> bool:
    return p is not None and not (isinstance(p, float) and np.isnan(p)) and p < 0.05


def compose(o: Out) -> None:
    # ------------------------------------------------------------------ data
    m = pd.read_csv(RES / "metrics.csv")
    gs = pd.read_csv(RES / "group_stats.csv").set_index("column")
    am = pd.read_csv(RES / "agents" / "metrics.csv")
    ags = pd.read_csv(RES / "agents" / "group_stats.csv").set_index("column")
    pr = pd.read_csv(RES / "final" / "paired.csv").set_index("column")
    po = pd.read_csv(RES / "final" / "pooled.csv").set_index("column")
    sz = pd.read_csv(RES / "final" / "size_adjusted.csv").set_index("column")
    pw = json.loads((RES / "final" / "power.json").read_text())
    top = pd.read_csv(RES / "top_rules.csv")
    scr = pd.read_csv(ROOT / "dataset" / "screened.csv")
    cand = pd.read_csv(ROOT / "dataset" / "candidates.csv")
    tcand = pd.read_csv(ROOT / "dataset" / "candidates_trailers.csv")
    pairs = pd.read_csv(ROOT / "dataset" / "pairs.csv")
    kinds = pd.read_csv(ROOT / "dataset" / "kinds.csv")
    tscj = json.loads((RES / "tsc_clean.json").read_text())

    H, L = m[m.group == "human"], m[m.group == "llm"]
    A = am[am.stratum == "other"]
    nH, nL, nA = len(H), len(L), len(A)
    b = lambda s: int(s.fillna(False).astype(bool).sum())
    clean_h, clean_l, clean_a = b(H.tsc_clean), b(L.tsc_clean), b(A.tsc_clean)
    pclean_h, pclean_l = b(H.tsc_project_clean), b(L.tsc_project_clean)
    tests_h, tests_l, tests_a = b(H.tests_passed), b(L.tests_passed), b(A.tests_passed)
    leg_h = int(H.tests_passed_legacy.fillna(False).astype(bool).sum()) if "tests_passed_legacy" in H else 0
    inst_h, inst_l = b(H.install_ok), b(L.install_ok)
    p_clean_ac = fisher_exact([[clean_a, nA - clean_a], [clean_l, nL - clean_l]])[1]
    mut = m[m.mutation_score.notna()]
    mut_h, mut_l = mut[mut.group == "human"], mut[mut.group == "llm"]
    mut_a = A[A.mutation_score.notna()]
    agents_named = sorted(A.main_agent.dropna().unique())
    nice = {"openhands": "OpenHands", "copilot": "Copilot", "cursor": "Cursor", "devin": "Devin", "jules": "Jules",
            "codex": "Codex"}
    agent_list = ", ".join(nice.get(a, a) for a in agents_named)
    kmap = dict(kinds[["full_name", "kind"]].values)
    same_kind = int(pairs.same_kind.sum())
    ratio = pairs.size_ratio
    n_tested = int(gs.mwu_p.notna().sum())
    n_sig = int((gs.holm_p < 0.05).sum())
    n_sig_pair = int((pr.holm_p < 0.05).sum()) if "holm_p" in pr else 0
    n_sig_oh = int((ags.holm_p_other_vs_human < 0.05).sum())
    n_sig_oc = int((ags.holm_p_other_vs_claude < 0.05).sum())
    n_sig_pool = int((po.holm_p < 0.05).sum())
    n_sig_size = int((sz.holm_p < 0.05).sum())
    md = pw["primary"]["cliffs_delta"]
    causes = pd.read_csv(ROOT / "dataset" / "test_failure_causes.csv")
    ch = causes[causes.repo_id.str.startswith("H")].cause_category
    cl = causes[causes.repo_id.str.startswith("L")].cause_category
    genuine_h, genuine_l = int((ch == "genuine failure").sum()), int((cl == "genuine failure").sum())
    decay_h = len(ch) - genuine_h
    mut_fail_h = int(((m.group == "human") & (m.mutation_status == "failed")).sum())
    ai_share = L.ai_commit_share
    llm_elig = int((scr[scr.group == "llm"].eligible).sum())
    llm_trailer_fail = int(scr[scr.group == "llm"].reason.fillna("").str.contains("AI-attributed").sum())
    n_llm_cand = int((scr.group == "llm").sum())

    def g(c):
        return gs.loc[c]

    def d(c):
        return f"δ~=~{g(c).cliffs_delta_llm_vs_human:+.2f}"

    def med(c, nd=2):
        return f"{fmt(g(c).median_human, nd)} vs. {fmt(g(c).median_llm, nd)}"

    def hp(c):
        return peq(g(c).holm_p)

    # ------------------------------------------------------------------ front matter
    o.header()
    lint, cc, reach, fan = g("lint_per_kloc"), g("cc_mean"), g("test_reach_pct"), g("fanout_mean")
    o.abstract(
        f"Coding agents now write whole repositories, yet comparisons of human and LLM code study single functions "
        f"generated for benchmark tasks. We present an empirical study of *whole TypeScript projects*: {nH} "
        f"human-written GitHub repositories pinned before 2021 and {nL} repositories whose commits carry Claude Code's "
        f"co-author signature, matched by project kind and size, plus {nA} projects built by other agents "
        f"({agent_list}). An automated, Docker-isolated pipeline installs each project from its own lockfile and "
        f"measures compilation with its own `tsconfig`, lint violations under one shared ESLint/SonarJS rule set, "
        f"complexity, duplication, structural testability from the import graph, and test effectiveness with the "
        f"project's own tests and StrykerJS mutation testing. The main expectation we drew from prior work fails for all three questions. "
        f"Agent-built projects have far fewer lint violations per KLOC (median {med('lint_per_kloc', 1)}, "
        f"{d('lint_per_kloc')}) and type-check cleanly more often ({clean_l}/{nL} vs. {clean_h}/{nH}), but their "
        f"functions are more complex (mean cyclomatic complexity {med('cc_mean')}, {d('cc_mean')}). Their tests "
        f"import more of the production code directly and pass far more often, while duplication, comment density "
        f"and test-to-code ratio do not differ. Projects from {words(len(agents_named))} other agents show the same "
        f"profile. Code, data and results are open source.",
        "LLM-generated code, coding agents, TypeScript, empirical study, static analysis, mutation testing, testability")

    # ------------------------------------------------------------------ I. Introduction
    o.h1("Introduction")
    o.p("LLM coding agents such as Claude Code, Cursor and Codex now plan, write, test and commit entire projects. "
        "Code that compiles and looks plausible may still hide defects, poor practices or weak tests, so it matters "
        "whether agent-built software differs from software written by people. Prior comparisons study Python or Java "
        "*functions* that researchers generated for benchmark tasks [2]--[4]. We instead study *whole, real-world "
        "projects* written in TypeScript, an ecosystem with its own failure modes [1]. Python is only the language of "
        "our measurement pipeline. This is an *empirical study*: we observe existing open-source projects rather than "
        "build a new analysis tool. We ask three questions, each with the expectation we derived from prior work "
        "before measuring:")
    o.bullets([
        "**RQ1 (code quality).** How do lint violations differ between human-written and LLM-generated TypeScript "
        "projects? *Expectation:* more serious (problem-type) issues in LLM code, as [3] and [4] report for "
        "high-severity issues and unused constructs.",
        "**RQ2 (complexity, maintainability, structural testability).** *Expectation:* simpler LLM code [4], "
        "similar duplication, and tests that reach at least as much code, since agents write tests as they go [5].",
        "**RQ3 (compilation).** Do LLM-generated projects have more compiler errors? *Expectation:* yes, from "
        "hallucinated APIs and types.",
    ])
    o.p("Our contributions are a frozen, kind- and size-matched dataset of agent-built and human-written TypeScript "
        "projects with verified authorship, an open-source measurement pipeline, and the answers to RQ1--RQ3, "
        "including a check that the findings hold for agents other than Claude Code.")

    # ------------------------------------------------------------------ II. Related work
    o.h1("Related Work")
    o.p("*Human vs. LLM code.* Molison et al. [2] ran SonarQube on human and LLM Python solutions at three difficulty "
        "levels. LLM code had fewer bugs and needed less effort to fix, but on competition-level tasks it introduced "
        "structural issues absent from the human solutions. Licorish et al. [3] analysed 72 Python tasks with Pylint, "
        "Radon and Bandit: GPT-4 code had more high-severity issues, while human code had more low-severity ones. "
        "Cotroneo et al. [4] compared over 500,000 Python and Java functions from humans and three LLMs. AI code was "
        "simpler and more repetitive, but had more unused constructs, hard-coded debugging and high-risk "
        "vulnerabilities. The three studies therefore agree that LLM code is *not uniformly worse*: it has fewer "
        "minor issues, and its risks concentrate in rarer, more serious ones that grow with task difficulty. They "
        "disagree on bug counts: [2] finds fewer bugs, [3] more severe issues. All three share one design, which is "
        "researcher-generated, function-level code in Python or Java.")
    o.p("*Tests and mutation.* TestPilot [5] showed that an LLM can write JavaScript unit tests with a median 70% "
        "statement coverage, so agent-built projects plausibly ship with substantial tests. Mutation testing measures "
        "whether such tests catch faults. LLMorpheus [6] found that LLM-written mutants capture bugs StrykerJS "
        "misses, and CDBench [7] found that LLMs write useful tests but often invalid mutants. Garg et al. [8] showed "
        "that SWE-Bench overstates agent ability, including on TypeScript, when task descriptions are unrealistic. "
        "Bruntink and van Deursen [9] linked a unit's size and fan-out to the test effort it needs, which we use as "
        "structural testability. *Gap:* no study compares *whole projects* that coding agents actually built and "
        "published with human projects, in TypeScript, on compilation, quality, structure and test effectiveness "
        "together. We fill that gap.")

    # ------------------------------------------------------------------ III. Study design
    o.h1("Study Design")
    o.h2("Dataset")
    o.p(f"*Discovery.* Candidates come from the GitHub search API (`bench/discover.py`) by two routes: README "
        f"phrases that advertise agent-built development, and the commit index searched for nine agents' own "
        f"signatures. This gave {len(cand):,} and {len(tcand):,} candidates. A screening stage (`bench/screen.py`) "
        f"applies fixed rules to each: a root `package.json` and `tsconfig.json`, a real `test` script, no "
        f"workspaces, ≥60% TypeScript, and 40~KB--1.5~MB of TypeScript. Projects without tests are therefore "
        f"excluded up front, because RQ2 needs a suite to measure.")
    o.p(f"*Authorship evidence.* A creation date after 2023 does not prove AI authorship, so the LLM group requires "
        f"positive evidence. `bench/authorship.py` detects ten agents' co-author trailers and bot authors, and a "
        f"project is eligible only if ≥50% of its last 100 commits carry one. This removed {llm_trailer_fail} of "
        f"{n_llm_cand} self-described LLM candidates. The selected projects have a median of "
        f"{fmt(100 * ai_share.median(), 0)}% agent-signed commits (a lower bound). Human projects are pinned to their "
        f"last commit before 2021-01-01, which predates Copilot's preview and ChatGPT.")
    o.p(f"*Selection and matching* (`bench/select_repos.py`). The LLM group is every eligible project whose main "
        f"agent is Claude Code ({nL}). Each is paired with an unused eligible human project (≥100 stars) by a cost of "
        f"|log size ratio|, plus ln~2 when the project kinds differ (library, CLI, service, UI app or extension, read "
        f"from `package.json`). {same_kind} of {len(pairs)} pairs share a kind. LLM projects are larger "
        f"(median human/LLM size ratio {fmt(ratio.median(), 2)}), because few large human projects pass screening, "
        f"so every count is normalised per KLOC and we test for size effects (Sec.~IV-D). The {nA} projects built "
        f"mainly by other agents ({agent_list}) form a third, unmatched group. "
        f"`dataset/repos.csv`, `repos_agents.csv` and `pairs.csv` freeze every commit analysed.")
    o.h2("Pipeline and measures")
    o.p("Each repository is cloned at its pin and copied into a fresh container of one Docker image (Node~22, pinned "
        "tools). Dependencies are installed with the project's own package manager and lockfile, and its own "
        "TypeScript version checks its own `tsconfig.json` (RQ3). Every project is linted with *one* shared ESLint~9 "
        "configuration (typescript-eslint and SonarJS recommended rules), ignoring its own disable comments; each "
        "violation is typed *problem* or *suggestion* (RQ1). RQ2 uses per-function cyclomatic [10] and cognitive [11] "
        "complexity, jscpd duplication and comment density. For *structural testability* (`bench/testability.py`) "
        "we build each project's import graph and measure internal fan-out per module [9], the share of production "
        "code that a test imports directly, and the share a test can reach transitively. *Test effectiveness* runs "
        "the project's own `test` script (15-minute limit) and, where it passes, StrykerJS mutation testing on a "
        "seeded sample of up to 10 production files. Suites that fail are re-run on a Node version from the "
        "project's era; a suite that cannot run counts as 0% passing and gets no mutation score. All counts are "
        "per KLOC of production code.")
    o.h2("Analysis plan")
    o.p(f"The primary test compares the human and Claude Code groups with two-sided Mann--Whitney U tests, Cliff's~δ "
        f"as effect size (magnitudes per [12]) and Holm correction [13] across the {n_tested} metrics. Robustness "
        f"checks are (i) Wilcoxon signed-rank tests over the matched pairs, (ii) a rank regression on group and "
        f"log size, (iii) human vs. all {nL + nA} agent-built projects, and (iv) other agents vs. each group. With "
        f"{nH} projects per group the test has 80% power for |δ|~≥~{fmt(md, 2)}, against "
        f"{fmt(pw['milestone_12']['cliffs_delta'], 2)} with the 12 per group of our milestone.")

    # ------------------------------------------------------------------ IV. Results
    o.h1("Results")
    rows = [["Metric (RQ)", "Human", "Claude", "Other", "δ", "p", "p pair"]]
    order = [("lint_per_kloc", 1), ("lint_problem_per_kloc", 1), ("lint_era_neutral_per_kloc", 1),
             ("any_per_kloc", 1), ("cc_mean", 2), ("cc_over10_pct", 1), ("cognitive_over15_pct", 1),
             ("functions_per_kloc", 0), ("dup_pct", 2), ("comment_density", 3), ("fanout_mean", 2),
             ("direct_test_pct", 0), ("test_reach_pct", 0), ("test_to_code", 2), ("test_pass_rate", 2),
             ("mutation_score", 2), ("tsc_errors_per_kloc", 2)]
    short = {"lint_per_kloc": "Lint violations/KLOC", "lint_problem_per_kloc": "Problem violations/KLOC",
             "lint_era_neutral_per_kloc": "Era-neutral viol./KLOC", "any_per_kloc": "Explicit `any`/KLOC",
             "cc_mean": "Mean cyclomatic CC", "cc_over10_pct": "% functions CC>10",
             "cognitive_over15_pct": "% functions cogn.>15", "functions_per_kloc": "Functions/KLOC",
             "dup_pct": "Duplicated lines %", "comment_density": "Comment density",
             "fanout_mean": "Internal fan-out/module", "direct_test_pct": "% code tested directly",
             "test_reach_pct": "% code reached by tests", "test_to_code": "Test-to-code ratio",
             "test_pass_rate": "Test pass rate", "mutation_score": "Mutation score",
             "tsc_errors_per_kloc": "tsc errors/KLOC"}
    rq = {"lint_per_kloc": 1, "lint_problem_per_kloc": 1, "lint_era_neutral_per_kloc": 1, "any_per_kloc": 1,
          "tsc_errors_per_kloc": 3}
    bold = []
    for c, nd in order:
        if c not in gs.index:
            continue
        r = g(c)
        if sig(r.holm_p):
            bold.append(len(rows))
        rows.append([f"{short[c]} ({rq.get(c, 2)})", fmt(r.median_human, nd), fmt(r.median_llm, nd),
                     fmt(ags.loc[c].median_other, nd) if c in ags.index else "--",
                     f"{r.cliffs_delta_llm_vs_human:+.2f}", pval(r.holm_p),
                     pval(pr.loc[c].holm_p) if c in pr.index else "--"])
    rows.append(["Compiles cleanly (3)", f"{clean_h}/{nH}", f"{clean_l}/{nL}", f"{clean_a}/{nA}", "",
                 pval(tscj["fisher_p"]), ""])
    rows.append(["Own tests pass (2)", f"{tests_h}/{nH}", f"{tests_l}/{nL}", f"{tests_a}/{nA}", "", "", ""])
    o.table("Medians per group. δ: Cliff's delta, Claude Code vs. human (+: higher in Claude Code). p: Holm-corrected "
            "Mann--Whitney U (Fisher exact for compiling). p pair: Holm-corrected Wilcoxon over matched pairs. "
            "Bold: p < 0.05",
            rows, [1.3, 0.47, 0.47, 0.43, 0.4, 0.43, 0.43], "tab:results", bold_rows=tuple(bold))
    o.p(f"Table~I summarises all metrics. {words(n_sig).capitalize()} of {n_tested} differ significantly between the "
        f"human and Claude Code groups after Holm correction, and {n_sig_pair} in the paired test. Fig.~1 shows the "
        f"per-project spread for six of them, including the other-agent group.")
    o.figure(RES / "figures" / "metrics_by_agent_group.png",
             "Per-project values for human, Claude Code and other-agent projects (dots) with group medians (bars). "
             "Violation panels use a log axis, with zero-violation projects drawn at its floor.", "fig:groups")

    o.h2("RQ1: Code quality")
    th = [r.split('/')[-1] for r in top[top.group == "human"].head(3).rule]
    tl = [r.split('/')[-1] for r in top[top.group == "llm"].head(3).rule]
    era, prob = g("lint_era_neutral_per_kloc"), g("lint_problem_per_kloc")
    o.p(f"Contrary to our expectation, Claude Code projects have far *fewer* violations: {med('lint_per_kloc', 1)} per "
        f"KLOC ({d('lint_per_kloc')}, Holm *p*{hp('lint_per_kloc')}), and fewer *problem*-type ones "
        f"({med('lint_problem_per_kloc', 1)}, {d('lint_problem_per_kloc')}). Human code is dominated by "
        f"{', '.join(f'`{x}`' for x in th)}; explicit `any` alone has a median of {med('any_per_kloc', 1)} per KLOC. "
        f"LLM code is dominated by {', '.join(f'`{x}`' for x in tl)}, which are structural rather than typing "
        f"issues. Part of the gap is an *era effect*, since older TypeScript lacked `unknown` and commonly used "
        f"`var` and `require`. Excluding 12 era-dependent rules still leaves {med('lint_era_neutral_per_kloc', 1)} "
        f"({d('lint_era_neutral_per_kloc')}, Holm *p*{hp('lint_era_neutral_per_kloc')}). The result agrees with "
        f"Molison et al. [2] rather than [3], [4]: we found no sign of more serious issues in LLM projects.")

    o.h2("RQ2: Complexity, maintainability and testability")
    o.p(f"Here the expectation from [4] is reversed. Claude Code functions are *more* complex: mean cyclomatic "
        f"complexity {med('cc_mean')} ({d('cc_mean')}, Holm *p*{hp('cc_mean')}), {med('cc_over10_pct', 1)}% of "
        f"functions above McCabe's threshold of 10, and {med('cognitive_over15_pct', 1)}% above Sonar's cognitive "
        f"threshold of 15 ({d('cognitive_over15_pct')}). Functions per KLOC "
        f"{'also fall' if sig(g('functions_per_kloc').holm_p) else 'do not differ significantly'} "
        f"({med('functions_per_kloc', 0)}), so agent code branches and nests more rather than merely packing more "
        f"code into each function. Duplication ({med('dup_pct')}), comment density ({med('comment_density', 3)}) "
        f"and test-to-code ratio ({med('test_to_code')}) do not differ (Holm *p*{hp('dup_pct')}, "
        f"*p*{hp('comment_density')}, *p*{hp('test_to_code')}).")
    o.p(f"*Structural testability* is mixed. Internal fan-out does not differ ({med('fanout_mean')} project "
        f"modules imported per module, Holm *p*{hp('fanout_mean')}), but Claude Code modules import fewer external "
        f"packages ({med('ext_fanout_mean')}, {d('ext_fanout_mean')}, Holm *p*{hp('ext_fanout_mean')}), so their "
        f"units have fewer dependencies to stub. Their tests import {med('direct_test_pct', 0)}% of production code "
        f"directly ({d('direct_test_pct')}, Holm *p*{hp('direct_test_pct')}; paired *p*{peq(pr.loc['direct_test_pct'].holm_p)}), "
        f"yet the share reachable from any test is similar ({med('test_reach_pct', 0)}%, Holm "
        f"*p*{hp('test_reach_pct')}): human suites reach code through a few entry points, agent suites test modules "
        f"one by one.")
    o.p(f"*Test effectiveness.* Own suites pass on Node~22 for {tests_l}/{nL} Claude Code projects but "
        f"{tests_h}/{nH} human ones. Re-running every failing human suite on a Node version from its era rescued "
        f"only {leg_h}. We diagnosed each failure from its logs (`dataset/test_failure_causes.csv`): {decay_h} of "
        f"{len(ch)} failing human suites have *decayed* (dependency rot, a needed browser or service, undeclared tools, "
        f"missing build output) and {genuine_h} fail on assertions, whereas {genuine_l} of {len(cl)} failing Claude "
        f"Code suites are genuine assertion failures. Mutation testing gave a valid score for {len(mut_h)} human and "
        f"{len(mut_l)} Claude Code projects (medians {fmt(mut_h.mutation_score.median(), 2)} vs. "
        f"{fmt(mut_l.mutation_score.median(), 2)}, Holm *p*{hp('mutation_score')}); Stryker's instrumented code "
        f"broke the old Jest set-up of {mut_fail_h} further human projects. Because mutation needs a passing suite, "
        f"this comparison is small and descriptive.")

    o.h2("RQ3: Compilation")
    o.p(f"Installation succeeded for {inst_h}/{nH} human and {inst_l}/{nL} Claude Code projects. With each project's "
        f"own compiler and configuration, {clean_l}/{nL} Claude Code and {clean_h}/{nH} human projects type-check with "
        f"no errors (Fisher *p*{peq(tscj['fisher_p'])}); counting only errors in project files, {pclean_l}/{nL} and "
        f"{pclean_h}/{nH} are clean. Errors per KLOC in project files do not differ ({med('tsc_errors_per_kloc')}, "
        f"Holm *p*{hp('tsc_errors_per_kloc')}). The answer to RQ3 is *no*: LLM projects do not have more compilation "
        f"errors{', and compile cleanly more often' if sig(tscj['fisher_p']) else ''}. Most human errors come from "
        f"decay (unresolvable packages, today's `@types` written in syntax the pinned compiler cannot parse), whereas "
        f"the few LLM errors are genuine type or configuration mistakes.")

    o.h2("Robustness and other agents")
    lsz = sz.loc["lint_per_kloc"]
    csz = sz.loc["cc_mean"]
    oc_diff = [short.get(c, c).lower() for c in ags.index if sig(ags.loc[c].holm_p_other_vs_claude)]
    o.p(f"The differences are not size effects: in a rank regression on group and log KLOC, {n_sig_size} metrics "
        f"keep a significant group effect after Holm correction, including lint violations (*p*{peq(lsz.holm_p)}) "
        f"and mean cyclomatic complexity (*p*{peq(csz.holm_p)}). The paired test over matched projects agrees "
        f"({n_sig_pair} metrics), and so does pooling all {nL + nA} agent-built projects against the human group "
        f"({n_sig_pool} metrics). The {nA} other-agent projects differ from human projects on {n_sig_oh} metrics "
        f"and from Claude Code on {'none' if not oc_diff else words(len(oc_diff)) + ' (' + ', '.join(oc_diff) + ')'}; "
        f"{clean_a}/{nA} type-check cleanly (vs. Claude Code: Fisher *p*{peq(p_clean_ac)}). Their tests reach less "
        f"code (median {fmt(ags.loc['test_reach_pct'].median_other, 0)}%), and mutation testing scored only "
        f"{len(mut_a)} of them.")

    # ------------------------------------------------------------------ V. Discussion
    o.h1("Discussion and Limitations")
    o.p("*Interpretation.* Agent-built projects look *cleaner* by every rule-based measure: fewer lint violations, "
        "almost no explicit `any`, clean compiles and passing tests. Agents run linters, type-checkers and tests in "
        "their own loop, and they write modern idioms. Much of the human disadvantage, however, is *decay*: four to "
        "eight years of ecosystem drift break installs, types and suites that once worked. Whether agent-built "
        "projects decay more slowly is an open question that only time can answer. Where agents are clearly worse "
        "is *complexity*: their functions branch and nest more. This reconciles prior work. Function-level studies "
        "find generated code simpler [4] because a benchmark function is small, whereas an agent building a whole "
        "feature concentrates logic in fewer, deeper functions, which matches the structural issues on hard tasks "
        "in [2]. For reviewers, complexity rather than lint is the place to look. Agents also write per-module unit "
        "tests, as TestPilot-style generation suggests [5], but those tests do not kill more mutants.")
    o.p("*Threats to validity.* (Construct) Co-author trailers show that an agent took part in commits, not that it "
        "wrote every line, so the LLM group is *agent-assisted*; our testability measures are static import "
        "reachability, not coverage. (Internal) The human group is necessarily older. Era-neutral rules, era-matched "
        "test re-runs and the failure diagnosis control for part of this, and a contemporary human group cannot be "
        "verified AI-free. (External) LLM projects are younger, less starred and larger than their human matches, "
        "and the other-agent group is small and unmatched. The results describe screened single-package projects "
        "with tests, not all TypeScript. (Conclusion) We report effect sizes, Holm-corrected and paired tests; the "
        "mutation comparison is underpowered.")

    # ------------------------------------------------------------------ VI. Conclusion
    o.h1("Conclusion")
    o.p(f"Across {nH + nL + nA} TypeScript projects, agent-built code is not the low-quality code our reading of "
        f"function-level studies led us to expect. It has far fewer lint violations, compiles at least as reliably, "
        f"and its tests pass and target modules directly, but its functions are more complex. The same profile holds "
        f"for {words(len(agents_named))} other agents. Future work should generate matched projects from the same "
        f"specifications with open models, and follow agent-built projects over time to see whether they decay. "
        f"The pipeline, dataset and raw results are at `github.com/tothang28012001/ts-llm-benchmark`.")
    o.refs()


def main() -> None:
    o = Out(OUT_DIR / PDF, tex_name="paper.tex", refs=REFS)
    compose(o)
    o.save()
    print("wrote", OUT_DIR / PDF, "and", OUT_DIR / "paper.tex")


if __name__ == "__main__":
    main()
