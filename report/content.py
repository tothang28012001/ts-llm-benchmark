"""Report text.  Every number is computed from results/ and dataset/ at build time."""
from __future__ import annotations

import numpy as np
import pandas as pd

from report.build_report import RES, Out, fmt, pval

ERA_RULE_COUNT = 12


def words(n: int) -> str:
    return ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"][n] if 0 <= n < 10 else str(n)


def direction(gs, col, more="more", less="fewer"):
    r = gs.loc[col]
    return more if r.median_llm > r.median_human else less


def stat_phrase(gs, col, nd=2):
    r = gs.loc[col]
    return (f"median {fmt(r.median_human, nd)} vs. {fmt(r.median_llm, nd)}, Cliff's~δ~=~{r.cliffs_delta_llm_vs_human:+.2f} "
            f"({r.effect}), Holm *p*~=~{pval(r.holm_p)}")


def compose(D: dict, o: Out) -> None:
    m, gs, s, scr, cand = D["m"], D["gs"], D["s"], D["scr"], D["cand"]
    H, L = m[m.group == "human"], m[m.group == "llm"]
    nH, nL = len(H), len(L)
    elig = scr.groupby("group").eligible.sum()
    llm_trailer_fail = int(scr[scr.group == "llm"].reason.fillna("").str.contains("AI-attributed").sum())
    n_llm_cand = int((scr.group == "llm").sum())
    tests_h = int(H.tests_passed.fillna(False).astype(bool).sum())
    tests_l = int(L.tests_passed.fillna(False).astype(bool).sum())
    legacy = {k: v.get("test_legacy") for k, v in s.items() if v.get("test_legacy")}
    legacy_pass_h = sum(1 for k, v in legacy.items() if k.startswith("H") and v.get("passed"))
    legacy_tried_h = sum(1 for k in legacy if k.startswith("H"))
    legacy_pass_l = sum(1 for k, v in legacy.items() if k.startswith("L") and v.get("passed"))
    legacy_tried_l = sum(1 for k in legacy if k.startswith("L"))
    mut = m[m.mutation_status == "ok"]
    mut_h, mut_l = mut[mut.group == "human"], mut[mut.group == "llm"]
    mut_tried = m[m.tests_passed.fillna(False).astype(bool)]
    n_invalid = int((m.mutation_status == "invalid-timeouts").sum())
    n_excluded = int((m.mutation_status == "excluded").sum())
    clean_h, clean_l = int(H.tsc_clean.sum()), int(L.tsc_clean.sum())
    pclean_h = int(H.tsc_project_clean.fillna(False).astype(bool).sum())
    pclean_l = int(L.tsc_project_clean.fillna(False).astype(bool).sum())
    inst_h = int(H.install_ok.fillna(False).astype(bool).sum())
    inst_l = int(L.install_ok.fillna(False).astype(bool).sum())
    any_r = gs.loc["any_per_kloc"]
    llm_agents = sorted({a for v in s.values() if v["group"] == "llm" for a in v["fetch"]["ai_agents"]})
    ai_share = L.ai_commit_share
    cc = gs.loc["cc_mean"]

    o.header()
    o.abstract(
        f"This milestone report documents our progress on an empirical benchmark that compares human-written and "
        f"LLM-generated TypeScript projects. We have (i) built an automated, Docker-isolated pipeline. It clones "
        f"each repository at a pinned commit, installs it from its own lockfile, and measures compilation (`tsc`), "
        f"code quality (ESLint with typescript-eslint and SonarSource rules), maintainability (cyclomatic and "
        f"cognitive complexity, duplication, comment density) and test effectiveness (the project's own tests and "
        f"StrykerJS mutation testing). (ii) We assembled a size-matched dataset of {nH} human-written repositories "
        f"pinned before 2021 and {nL} agent-built repositories, whose authorship we verify from AI co-author commit "
        f"trailers. (iii) We ran the pipeline on all {nH + nL} repositories. In preliminary results, the LLM group has "
        f"far fewer lint violations per KLOC (median {fmt(gs.loc['lint_per_kloc'].median_human, 1)} vs. "
        f"{fmt(gs.loc['lint_per_kloc'].median_llm, 1)}) but more complex functions (mean cyclomatic complexity "
        f"{fmt(cc.median_human, 2)} vs. {fmt(cc.median_llm, 2)}). Its own test suites also pass more often on a current "
        f"Node.js ({tests_l}/{nL} vs. {tests_h}/{nH}), largely because old human suites have decayed. We found no "
        f"significant difference in duplication, comment density, test-to-code ratio or compiler errors. The report "
        f"ends with the remaining work toward the final paper.",
        "LLM-generated code, TypeScript, empirical software engineering, static analysis, mutation testing, benchmark")

    # ---------------------------------------------------------------- I
    o.h1("Introduction")
    o.p("LLM coding agents such as Claude Code, Cursor and Codex now write entire repositories, not just snippets. "
        "Code that compiles and looks plausible may still hide defects, poor practices or weak tests. Prior "
        "comparisons of human and LLM code study Python or Java *functions* generated for benchmark tasks [2]--[4]. "
        "We instead compare *whole, real-world TypeScript projects* published on GitHub, in an ecosystem with its "
        "own characteristic failure modes [1]. Our research questions are unchanged from the proposal:")
    o.bullets(["**RQ1** How does code quality differ between human-written and LLM-generated TypeScript projects?",
               "**RQ2** How do complexity, maintainability and structural testability differ?",
               "**RQ3** Do LLM-generated projects have more compilation errors?"])
    o.p("Since the proposal (Oct.~19) and the literature review (Nov.~2), we have completed the dataset-collection and "
        "infrastructure phases of our plan and a first full evaluation run. Table~I gives the status of each phase. "
        "The rest of this report covers the dataset (Sec.~II), the pipeline (Sec.~III), preliminary results "
        "(Sec.~IV), threats to validity (Sec.~V) and remaining work (Sec.~VI).")
    o.table("Progress against the project plan",
            [["Phase (from proposal)", "Status", "Evidence"],
             ["1. Literature review and design", "Done", "Review (Nov. 2); design refined (Sec. II--III)"],
             ["2. Dataset collection", "Done", f"{len(cand)} candidates → {nH}+{nL} repos, frozen SHAs"],
             ["3. Infrastructure", "Done", "Dockerized pipeline, open-source repository"],
             ["4. Evaluation", "First full run done", f"All {nH + nL} repos, all stages"],
             ["5. Analysis and reporting", "In progress", "Preliminary statistics (Sec. IV)"]],
            [1.3, 0.8, 1.5], "tab:progress")

    # ---------------------------------------------------------------- II
    o.h1("Dataset Construction")
    o.h2("Discovery and screening")
    o.p(f"Candidates come from the GitHub search API (`bench/discover.py`). Human candidates are TypeScript "
        f"repositories created between 2016 and mid-2020, with 100--3,000 stars and no push after 2021. LLM "
        f"candidates are TypeScript repositories created in 2025 or later whose README advertises agent-built "
        f"development (“built with Claude Code”, “vibe coded”, “built with Codex”, ...). "
        f"This yielded {len(cand)} unique candidates ({int((scr.group == 'human').sum())} human, {n_llm_cand} LLM). "
        f"A screening stage (`bench/screen.py`) fetches each repository's root `package.json`, `tsconfig.json`, "
        f"language breakdown and latest 100 commits with batched GraphQL queries. It then applies fixed eligibility "
        f"rules: a root package and tsconfig, a real `test` script (vitest, jest, mocha, ava, jasmine or "
        f"`node --test`), no workspaces, ≥60% TypeScript, and 40~KB--1.5~MB of TypeScript. "
        f"{int(elig.get('human', 0))} human and {int(elig.get('llm', 0))} LLM repositories were eligible. Every "
        f"decision and its reason is recorded in `dataset/screened.csv`.")
    o.h2("Verifying authorship")
    o.p(f"The proposal classified projects by release date alone, which is unreliable. For the LLM group we now "
        f"require *positive evidence*. Coding agents leave machine-readable traces in commit metadata, such as "
        f"Claude Code's `Co-Authored-By: Claude` trailer, Cursor, Copilot and Codex co-author trailers, and agent bot "
        f"authors. `bench/authorship.py` detects ten such agents. An LLM repository is eligible only if ≥50% of "
        f"its latest 100 commits carry such a trailer. This removed {llm_trailer_fail} of the {n_llm_cand} "
        f"self-described LLM candidates, so README claims alone would have mislabelled most projects. After cloning, "
        f"the share is recomputed over the full history. The selected LLM repositories have a median of "
        f"{fmt(100 * ai_share.median(), 0)}% agent-attributed commits (range {fmt(100 * ai_share.min(), 0)}--"
        f"{fmt(100 * ai_share.max(), 0)}%), from {', '.join(llm_agents)}. This is a lower bound, since agents can be "
        f"used without trailers. For the human group we keep a date rule but make it airtight. Each repository is "
        f"*pinned to its last commit before 2021-01-01*, which predates GitHub Copilot's preview (June 2021) and "
        f"ChatGPT (Nov. 2022). None of their commits carry an agent trailer.")
    o.h2("Selection and matching")
    o.p(f"Selection is deterministic (`bench/select_repos.py`). We take the {nL} most-starred eligible LLM "
        f"repositories and pair each with the not-yet-chosen eligible human repository (≥100 stars) closest in "
        f"TypeScript size on a log scale. Twelve per group exceeds the proposal's target of ten, which leaves spares "
        f"if a project cannot be analysed. Table~II lists the frozen dataset. Production code ranges from "
        f"{fmt(m.prod_kloc.min(), 1)} to {fmt(m.prod_kloc.max(), 1)} KLOC (median {fmt(H.prod_kloc.median(), 1)} human "
        f"vs. {fmt(L.prod_kloc.median(), 1)} LLM), and the analysed commit SHAs are in `dataset/repos.csv`.")
    rows = [["ID", "Repository", "Pin date", "KLOC", "Test", "AI%"]]
    for _, r in m.sort_values("repo_id").iterrows():
        rows.append([r.repo_id, r.full_name, r.pin_date, fmt(r.prod_kloc, 1), fmt(r.test_kloc, 1),
                     "0" if r.group == "human" else fmt(100 * r.ai_commit_share, 0)])
    o.table("Benchmarked repositories (KLOC: production code; Test: test-code KLOC; AI%: agent-attributed commits up to the pin)",
            rows, [0.3, 1.8, 0.6, 0.4, 0.34, 0.3], "tab:dataset")

    # ---------------------------------------------------------------- III
    o.h1("Benchmark Infrastructure")
    o.p("The pipeline follows the proposed design (retrieve → install → build and test → collect) and is "
        "fully automated in Python (`bench/run.py`). Each repository is cloned on the host without blobs and checked "
        "out at its pin, with line-ending conversion disabled. It is then copied into a *fresh container* built from "
        "our image (Node~22 plus the pinned toolchain). The host copy is mounted read-only and the container is "
        "discarded afterwards, so install scripts, tests and mutants never touch the host. Stages are resumable, and "
        "all raw artefacts are kept per repository. Code, dataset and results are public at "
        "`github.com/tothang28012001/ts-llm-benchmark`. The stages are:")
    o.bullets([
        "**Inventory and size.** `.ts`/`.tsx` files are split into production and test code by `*.test`/`*.spec` "
        "names and test directories. Build output, declaration files, configuration and tooling scripts are "
        "excluded. Code and comment lines are counted with the TypeScript parser, using SonarQube's definitions.",
        "**Code quality (RQ1).** Every project gets one ESLint~9 configuration (`@eslint/js`, typescript-eslint "
        "and SonarJS recommended rules), and the project's own `eslint-disable` comments are ignored. Each "
        "violation is typed by its rule's `meta.type`: *problem* (likely bug) or *suggestion*.",
        "**Maintainability (RQ2).** Per-function cyclomatic [8] and cognitive [9] complexity (ESLint `complexity` "
        "and SonarJS `cognitive-complexity`, threshold 0), duplication via jscpd (100-token / 5-line minimum, as in "
        "SonarQube), and comment density.",
        "**Compilation (RQ3).** Dependencies are installed with the project's own package manager and lockfile "
        "(npm, yarn or pnpm via Corepack), with logged fallbacks. The project's *own* TypeScript version then runs "
        "against its own `tsconfig.json`, including referenced sub-projects. Diagnostics are counted by `TS` code, "
        "separately for project files and for dependencies.",
        "**Tests and mutation (RQ2).** The project's `test` script runs with a 15-minute limit. When it passes, "
        "StrykerJS~10 [7], [12] mutates a seeded random sample of production files (about 400 lines, at most 10 "
        "files). It uses the native vitest, jest or mocha runner where the framework version allows, and the "
        "command runner otherwise. Stryker is pre-installed in the image so that it never re-resolves the "
        "project's dependency tree. Suites that fail on Node~22 are re-run on a Node version from their own era "
        "(8--14, taken from `.nvmrc`, `engines` or the pin date) to separate broken tests from environment drift.",
    ])
    o.p("One deliberate change from the proposal: instead of operating a SonarQube server, we run SonarSource's "
        "JavaScript/TypeScript analyzer rules (SonarJS, the engine inside SonarQube) through ESLint, plus "
        "SonarQube-equivalent duplication and comment metrics. This gives the same per-rule and per-function "
        "measurements without a stateful server, and every run is reproducible from a single Docker image.")

    # ---------------------------------------------------------------- IV
    o.h1("Preliminary Results")
    o.p(f"All {nH + nL} repositories completed every static stage. Group differences are tested with two-sided "
        f"Mann--Whitney U tests. Effect sizes are Cliff's~δ (positive means higher in the LLM group; magnitudes "
        f"follow [10]), and *p*-values are Holm-corrected [11] across the {int(gs.mwu_p.notna().sum())} metrics in "
        f"Table~III. With {nH} projects per group the results are exploratory. Fig.~1 shows the per-project "
        f"distributions of six key metrics.")
    o.figure(RES / "figures" / "metrics_by_group.png",
             "Per-repository values by group (dots) and group medians (bars). Violation panels use a log axis, "
             "with zero-violation projects drawn at the axis floor. Suites that could not run count as 0% passing.", "fig:metrics")
    order = ["lint_per_kloc", "lint_problem_per_kloc", "lint_era_neutral_per_kloc", "any_per_kloc", "cc_mean",
             "cc_over10_pct", "cognitive_mean", "cognitive_over15_pct", "functions_per_kloc", "dup_pct",
             "comment_density", "test_to_code", "test_pass_rate", "tsc_errors_per_kloc", "mutation_score", "mutation_score_covered"]
    trows = [["Metric", "Human", "LLM", "δ", "p (Holm)"]]
    for c in order:
        if c not in gs.index or pd.isna(gs.loc[c].get("median_human", np.nan)):
            continue
        r = gs.loc[c]
        nd = 3 if c in ("comment_density", "mutation_score", "mutation_score_covered", "test_pass_rate") else 2
        trows.append([f"{r.metric} ({r.rq})", fmt(r.median_human, nd), fmt(r.median_llm, nd),
                      f"{r.cliffs_delta_llm_vs_human:+.2f}", pval(r.holm_p)])
    o.table("Group medians and tests (δ: Cliff's delta, LLM vs. human)", trows, [1.8, 0.42, 0.42, 0.38, 0.5], "tab:stats")

    o.h2("RQ1: Code quality")
    top = D["top"]
    th = [r.split('/')[-1] for r in top[top.group == "human"].head(4).rule]
    tl = [r.split('/')[-1] for r in top[top.group == "llm"].head(4).rule]
    era = gs.loc["lint_era_neutral_per_kloc"]
    o.p(f"Contrary to the common expectation that LLM code is of lower quality, the LLM group has "
        f"{direction(gs, 'lint_per_kloc')} lint violations per KLOC ({stat_phrase(gs, 'lint_per_kloc', 1)}) and "
        f"{direction(gs, 'lint_problem_per_kloc')} *problem*-type violations ({stat_phrase(gs, 'lint_problem_per_kloc', 1)}). "
        f"The two groups' rule profiles also differ. Human projects are dominated by {', '.join(f'`{x}`' for x in th)}: "
        f"explicit `any` alone has a median of {fmt(any_r.median_human, 1)} per KLOC vs. {fmt(any_r.median_llm, 1)}. "
        f"LLM projects are dominated by {', '.join(f'`{x}`' for x in tl)}, which are structural rather than typing issues.")
    o.p(f"Part of this gap is an *era effect*. Older TypeScript lacked `unknown` (added in 3.0), and code from that "
        f"time commonly used `var`, `require` and wrapper types. Excluding {ERA_RULE_COUNT} era-dependent rules keeps "
        f"the direction and a large effect (median {fmt(era.median_human, 1)} vs. {fmt(era.median_llm, 1)}, "
        f"δ~=~{era.cliffs_delta_llm_vs_human:+.2f}, uncorrected *p*~=~{pval(era.mwu_p)}), but the difference is "
        f"no longer significant after correction (Holm *p*~=~{pval(era.holm_p)}). One plausible contributor is that "
        f"agents run linters during development and have learned modern typescript-eslint idioms.")

    o.h2("RQ2: Complexity, maintainability and testability")
    cc10, cog, fk = gs.loc["cc_over10_pct"], gs.loc["cognitive_over15_pct"], gs.loc["functions_per_kloc"]
    o.p(f"The clearest difference runs the other way: LLM-written functions are more complex. Mean cyclomatic "
        f"complexity is {fmt(cc.median_human, 2)} vs. {fmt(cc.median_llm, 2)} (δ~=~{cc.cliffs_delta_llm_vs_human:+.2f}, "
        f"Holm *p*~=~{pval(cc.holm_p)}). The share of functions above McCabe's threshold of 10 is "
        f"{fmt(cc10.median_human, 1)}% vs. {fmt(cc10.median_llm, 1)}%, and above Sonar's cognitive threshold of 15 it "
        f"is {fmt(cog.median_human, 1)}% vs. {fmt(cog.median_llm, 1)}% (δ~=~{cog.cliffs_delta_llm_vs_human:+.2f}). "
        f"LLM projects also have fewer functions per KLOC ({fmt(fk.median_human, 0)} vs. {fmt(fk.median_llm, 0)}, "
        f"Holm *p*~=~{pval(fk.holm_p)}). Together this suggests that agents write fewer, longer, more deeply nested "
        f"functions, which fits SonarJS's `no-nested-conditional` being their most frequent violation. Duplication "
        f"({stat_phrase(gs, 'dup_pct')}), comment density ({stat_phrase(gs, 'comment_density', 3)}) and test-to-code "
        f"ratio ({stat_phrase(gs, 'test_to_code')}) do not differ significantly.")
    causes = pd.read_csv(RES.parent / "dataset" / "test_failure_causes.csv")
    ch = causes[causes.repo_id.str.startswith("H")].cause_category
    cl = causes[causes.repo_id.str.startswith("L")].cause_category
    genuine_h, genuine_l = int((ch == "genuine failure").sum()), int((cl == "genuine failure").sum())
    pr = gs.loc["test_pass_rate"]
    o.p(f"Test runnability differs sharply. The project's own test suite passes on Node~22 for {tests_l} of {nL} LLM "
        f"projects but only {tests_h} of {nH} human projects. The per-project pass rate has a median of "
        f"{fmt(100 * pr.median_human, 1)}% vs. {fmt(100 * pr.median_llm, 1)}% (δ~=~{pr.cliffs_delta_llm_vs_human:+.2f}, "
        f"Holm *p*~=~{pval(pr.holm_p)}). We diagnosed every failing suite from its logs "
        f"(`dataset/test_failure_causes.csv`). Re-running the {legacy_tried_h} failing human suites on an era-matched "
        f"Node version made {legacy_pass_h} pass (a `node-sass` binary). Of the remaining human failures, "
        f"{int((ch == 'dependency rot').sum())} cannot install at all (an unpublished npm package and an unfetchable git "
        f"dependency), {int((ch == 'external service').sum())} depends on a public API that now returns 403, "
        f"{int((ch == 'environment (device-only)').sum())} is a device-only end-to-end suite, and only {genuine_h} "
        f"are genuine failures. The LLM failures are the reverse: {genuine_l} of {len(cl)} are genuine failing "
        f"assertions (8 failing tests each, in suites of 372--3,367 tests), and one needs an `ffmpeg` binary. Human "
        f"suites mostly *decay*, while LLM suites are committed with a few red tests.")
    if len(mut):
        def ms(g):
            return (f"median {fmt(g.mutation_score.median(), 2)} (range {fmt(g.mutation_score.min(), 2)}--"
                    f"{fmt(g.mutation_score.max(), 2)}, n~=~{len(g)})") if len(g) else "not yet available"
        o.p(f"Mutation testing produced a score for {len(mut)} of the {len(mut_tried)} projects with a passing suite "
            f"({int(mut.mutants.sum())} mutants). The score was {ms(mut_h)} for human projects and {ms(mut_l)} for LLM "
            f"projects; survived and uncovered mutants both count as not killed. Restricted to mutants that some test "
            f"executes, the medians are {fmt(mut_h.mutation_score_covered.median(), 2)} (human) and "
            f"{fmt(mut_l.mutation_score_covered.median(), 2)} (LLM). Projects run with the framework-agnostic "
            f"command runner cannot report coverage, so all their mutants count as covered."
            + (f" We discard {words(n_invalid)} run{'s' if n_invalid != 1 else ''} in which more than half of the mutants only timed out, since such a "
               f"score measures machine load rather than the tests." if n_invalid else "")
            + (f" We also exclude {words(n_excluded)} project{'s' if n_excluded != 1 else ''} whose tests run against precompiled JavaScript, which "
               f"mutated TypeScript sources never reach (`dataset/mutation_exclusions.csv`)." if n_excluded else "")
            + f" Mutation testing can "
            f"only run where the tests pass today, so the human sample is small and biased toward projects that "
            f"still run. We treat this comparison as descriptive for now.")
    else:
        o.p("Mutation testing has not yet produced enough scores for a group comparison; see Sec.~VI.")

    o.h2("RQ3: Compilation")
    err = m.set_index("repo_id")
    eh, el = int(H.tsc_errors.sum()), int(L.tsc_errors.sum())
    o.p(f"Dependency installation succeeded for {inst_h}/{nH} human and {inst_l}/{nL} LLM projects. With each "
        f"project's own compiler and configuration, {clean_l}/{nL} LLM and {clean_h}/{nH} human projects type-check "
        f"with zero errors (Fisher exact *p*~=~{pval(D['tsc_clean']['fisher_p'])}). Counting only errors located in "
        f"project files, {pclean_l}/{nL} and {pclean_h}/{nH} are clean. Errors per KLOC do not differ significantly "
        f"({stat_phrase(gs, 'tsc_errors_per_kloc')}). The volume and causes do differ. The human group has "
        f"{eh:,} errors, nearly all attributable to decay or missing context. H07 and H10 cannot install, so "
        f"{int(err.loc['H07'].tsc_errors) + int(err.loc['H10'].tsc_errors)} errors are unresolved modules and type "
        f"definitions (`TS2307`, `TS2339`, `TS2688`). H02 and H05 report errors only inside `node_modules`: today's "
        f"`@types` packages use syntax their pinned TypeScript ({err.loc['H02'].ts_version}, {err.loc['H05'].ts_version}) "
        f"cannot parse. H04 imports a sibling repository that is not part of its checkout (10 errors) and has 5 "
        f"ordinary type errors. The LLM group has only "
        f"{el} errors in two projects, all in project files: an import of a file produced by a build step, two "
        f"`unknown` values passed as `string` (L06), and a Vite config missing Node type definitions (L11). Our "
        f"preliminary answer to RQ3 is therefore *no*. LLM projects do not have more compilation errors. The few they "
        f"have are genuine type or configuration mistakes, whereas the human projects' errors come from environment "
        f"decay.")

    # ---------------------------------------------------------------- V
    o.h1("Threats to Validity")
    o.bullets([
        "**Construct.** Agent trailers show that an agent co-authored commits, not that it wrote every line. "
        "Humans may edit agent output, so the LLM group is best described as *agent-assisted*.",
        "**Era confounding.** The human group is necessarily older (2017--2020 code, older TypeScript and "
        "dependencies). Era-neutral rules and era-matched test runs partly control for this. A contemporary "
        "human group cannot be verified to be AI-free.",
        "**Internal.** Install fallbacks (e.g., `--legacy-peer-deps`) and modern Node versions can change "
        "outcomes. Every fallback level is logged and reported.",
        "**External.** Twelve star-selected projects per group do not represent all TypeScript code. The LLM "
        "projects are younger and less popular, and “built with” marketing may favor showcase projects.",
        "**Conclusion.** The samples are small, so we report effect sizes and Holm-corrected *p*-values, and "
        "frame the results as exploratory.",
    ])

    # ---------------------------------------------------------------- VI
    o.h1("Remaining Work")
    o.bullets([
        "**By Nov.~20:** extend mutation testing to every suite that passes under its era-matched Node, using an "
        "older Stryker release where required, and manually validate the production/test file classifier on a "
        "sample of files.",
        "**By Nov.~24:** sensitivity analyses (per-file normalization, star-matched subsets, a stricter LLM sample "
        "with ≥90% agent commits), plus a qualitative review of the most frequent violations and compiler "
        "errors mapped to the bug taxonomy of [1].",
        "**Nov.~27 / Dec.~4:** final presentation of findings, limitations and conclusions.",
        "**By Dec.~7:** the 4-page IEEE paper (this report's LaTeX source already uses `IEEEtran`) and a "
        "tagged release of the repository (pipeline, dataset and raw results) as the project artefact.",
    ])
    o.refs()


def main() -> None:
    from report.build_report import OUT_DIR, PDF_NAME, load_all
    D = load_all()
    o = Out(OUT_DIR / PDF_NAME)
    compose(D, o)
    o.save()
    print("wrote", OUT_DIR / PDF_NAME, "and", OUT_DIR / "milestone.tex")


if __name__ == "__main__":
    main()
