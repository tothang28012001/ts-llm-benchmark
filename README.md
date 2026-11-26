# ts-llm-benchmark

An empirical study comparing **human-written** and **LLM-agent-built** TypeScript projects on
code quality, complexity, structural testability, test effectiveness and compilation. The study is
observational: it measures existing open-source projects rather than scoring models on fixed
tasks. Every studied project is TypeScript; Python is only the language of the measurement
pipeline. What others can reuse is the automated, containerised pipeline and the frozen dataset.

CMPT 479 D100 course project (Simon Fraser University). Authors: Simon Xie, Sukhdip Kandola, Thang To.
Licensed under MIT (see `LICENSE`).

* **Final paper:** [`report/CMPT479 - Final Paper.pdf`](report/CMPT479%20-%20Final%20Paper.pdf)
  (LaTeX source: `report/paper.tex`, `\documentclass[10pt,conference]{IEEEtran}`)
* Milestone report: [`report/CMPT479 - Milestone Progress Report.pdf`](report/CMPT479%20-%20Milestone%20Progress%20Report.pdf)

## Research questions

1. **RQ1** How does code quality (lint violations) differ between human-written and LLM-generated TypeScript projects?
2. **RQ2** How do complexity, maintainability and structural testability differ?
3. **RQ3** Do LLM-generated projects have more compilation errors?

## Dataset at a glance

| Group | IDs | n | How it is defined | File |
|---|---|---|---|---|
| Human-written | H01–H36 | 36 | pinned to the last commit before 2021-01-01 (before Copilot and ChatGPT) | `dataset/repos.csv` |
| Claude Code | L01–L36 | 36 | ≥50% of the last 100 commits carry Claude Code's co-author trailer; each paired with a human project | `dataset/repos.csv`, `dataset/pairs.csv` |
| Other agents | A01–A22 | 22 | built mainly by Cursor, Copilot, Devin, Jules, OpenHands or Codex, by the same trailer rule; unmatched | `dataset/repos_agents.csv` |

* H01–H12 / L01–L12 are the milestone pairs (matched by size). H13–H36 / L13–L36 were added for the
  final study and are matched by **project kind** (library, CLI, service, UI app, extension, from
  `package.json`, `dataset/kinds.csv`) and **size**. Every pair is in `dataset/pairs.csv`.
* Every analysed commit SHA is frozen in the dataset CSVs. `dataset/screened*.csv` records every
  screening decision and its reason. Exclusions with reasons: `dataset/agents_exclusions.csv`
  (not measurable) and `dataset/mutation_exclusions.csv` (mutation score not meaningful).
* Projects without a real `test` script are excluded at screening. A suite that cannot run counts
  as 0% passing and gets no mutation score.

## Pipeline

```
discover ──► screen ──► kind ──► select ──► run (per repo, fresh Docker container) ──► analyze ──► paper
GitHub       GraphQL    package   kind+size   fetch → inventory → loc → lint → dup →      stats,
search       filters    .json     matched     install → tsc → test → mutate               figures
```

| Stage | Tool | Output |
|---|---|---|
| Discovery | GitHub search API: README phrases, and each agent's commit signature (`bench/discover.py [--by-trailer]`) | `dataset/candidates*.csv` |
| Screening | GitHub GraphQL: package.json, tsconfig, test runner, TS size, AI-commit share, pre-2021 pin (`bench/screen.py`) | `dataset/screened*.csv` |
| Project kind | rules over the root package.json (`bench/kind.py`) | `dataset/kinds.csv` |
| Selection | every eligible Claude Code project + kind- and size-matched human project (`bench/select_repos.py --extend`); other agents (`--agents`) | `dataset/repos.csv`, `pairs.csv`, `repos_agents.csv` |
| Authorship | AI-agent commit trailers over the full history (`bench/authorship.py`) | `summary.json → fetch` |
| Size / comments | TypeScript parser (`tools/loc.mjs`) | `loc.json` |
| Code quality (RQ1) | one ESLint 9 config for all: typescript-eslint + SonarJS recommended, inline disables ignored (`tools/lint.mjs`) | `lint.json` |
| Complexity (RQ2) | ESLint `complexity` (cyclomatic) and `sonarjs/cognitive-complexity`, per function | `lint.json` |
| Duplication (RQ2) | jscpd, 100-token / 5-line threshold | `jscpd/jscpd-report.json` |
| Structural testability (RQ2) | import graph: internal fan-out per module, % code imported directly by tests, % code reachable from tests (`bench/testability.py`) | `results/testability.csv` |
| Compilation (RQ3) | install from the project's own lockfile, then its own `tsc` + `tsconfig.json` (`tools/tscheck.mjs`) | `tsc.json` |
| Tests (RQ2) | the project's own `test` script; failing suites re-run on an era-matched Node (`bench/legacy_tests.py`) | `test.log` |
| Test effectiveness (RQ2) | StrykerJS 10 on a seeded sample of up to 10 production files (`tools/mutate.mjs`) | `stryker.json` |

Every repository is analysed in a fresh container built from `docker/Dockerfile`. The host
checkout is mounted read-only, and the container is deleted afterwards.

### Statistics

* `bench/analyze.py`: human vs. Claude Code. Two-sided Mann–Whitney U, Cliff's δ, Holm correction.
* `bench/compare_agents.py`: other agents vs. each group, with the same tests.
* `bench/final_stats.py`: robustness checks:
  * Wilcoxon signed-rank tests over the matched pairs
  * a rank regression on group and log size (size control)
  * human vs. all agent-built projects
  * a power simulation for the actual group sizes
* `bench/sensitivity.py`: the sensitivity analyses promised in the milestone report:
  * a stricter Claude Code sample (≥90% of commits agent-signed)
  * only Claude Code projects with ≥10 stars
  * lint, `any` and compiler errors per production file instead of per KLOC
  * within Claude Code, the correlation of stars with every metric
* `bench/classifier_sample.py`: manual check of the production/test file split. It draws a seeded
  sample of 100 files; the verdict for each, judged by hand, is in `dataset/classifier_validation.csv`
  (97/100 correct).

### Mutation-testing fixes after the first run

Every Stryker failure was traced to its log. Two problems in `tools/mutate.mjs` were fixed and the
affected projects (H18, H19, H27) re-run:

* For Jest versions too old for Stryker's Jest plugin, the command runner ran `npx jest --ci` and
  dropped the project's own `--config`, so the initial test run failed. It now keeps the arguments
  the project's `test` script passes to Jest.
* TypeScript before 3.7 ignores the `// @ts-nocheck` that Stryker's `disableTypeChecks` adds, so
  ts-jest type-checks the instrumented code. As a last attempt, after every other attempt failed
  on TypeScript diagnostics, the runner wraps the project's Jest config with ts-jest diagnostics off.

Neither change affects a project that was scored before: both only apply where earlier attempts failed.
H18, H19 and H27, and every human or Claude Code project that had exceeded the 20-minute limit
(H21, L17, L21, L22, L31, L32), were then re-run with `--mutate-minutes 60`. This added scores for
H18, H21, H27, L21, L22 and L31 (11 human and 26 Claude Code projects are now scored); H19 and L17
still time out, and L32 has a test that fails only under Stryker. No static measurement changed.

## Setup

Requirements: Python 3.11+, Node 22+, Docker, and an authenticated `gh` CLI (only for discovery,
screening and `bench.kind`).

```bash
pip install -r requirements.txt
cd tools && npm ci && cd ..
docker build -t ts-llm-bench:1 -f docker/Dockerfile .
```

## Reproducing the results

The dataset CSVs and all per-project results are committed, so the statistics, figures and
paper can be regenerated without re-running any project:

```bash
python -m bench.testability      # import-graph testability (needs the clones in work/repos/, see below)
python -m bench.analyze          # results/metrics.csv, group_stats.csv, figures
python -m bench.compare_agents   # results/agents/
python -m bench.final_stats      # results/final/ (paired, pooled, size-adjusted, power)
python -m bench.sensitivity      # results/final/sensitivity*.csv
python -m bench.classifier_sample  # summary of the manual file-classifier check
python -m report.paper           # report/CMPT479 - Final Paper.pdf and report/paper.tex
```

Re-measuring the projects (executes their code in Docker; a few hours with mutation testing):

```bash
python -m bench.run --jobs 3                       # H01-H36 and L01-L36 (clones into work/repos/)
BENCH_RAW=$PWD/results/raw_agents python -m bench.run --dataset dataset/repos_agents.csv --jobs 3
python -m bench.legacy_tests                       # failing suites again, on a Node version from the project's era
python -m bench.run --static-only --jobs 3         # alternative: static stages only, no repository code runs
```

On PowerShell, set the variable with `$env:BENCH_RAW = "$PWD/results/raw_agents"` and clear it with
`Remove-Item Env:BENCH_RAW` before running `bench.analyze`.

Rebuilding the dataset from scratch (GitHub search results change over time, so this will not
give exactly the frozen dataset):

```bash
GH_TOKEN=$(gh auth token) python -m bench.discover
GH_TOKEN=$(gh auth token) python -m bench.discover --by-trailer
GH_TOKEN=$(gh auth token) python -m bench.screen
GH_TOKEN=$(gh auth token) python -m bench.screen --input dataset/candidates_trailers.csv --output dataset/screened_trailers.csv
GH_TOKEN=$(gh auth token) python -m bench.kind
python -m bench.select_repos            # milestone pairs H01-H12 / L01-L12
python -m bench.select_repos --agents   # other agents A01...
python -m bench.select_repos --extend   # final study: H13.. / L13.., kind- and size-matched; A21.. (Codex)
```

### Quick demo (about one minute)

Re-runs every stage on one project (L01, about 1,000 lines of code) into `demo/raw/` without
touching the committed results, so the output can be compared with `results/raw/L01/`.
It needs `work/repos/L01`, which a full `bench.run` clones.

```powershell
$env:BENCH_RAW = "$PWD\demo\raw"; python -m bench.run --only L01 --force --jobs 1 --mutate-minutes 5
```

### Explore the projects in a browser

A small local web app for clicking through the projects: each project's pipeline result stage by
stage, its position against the human and AI medians, its real source with every counted lint
problem underlined and every mutant the tests missed marked, its test logs, and a button that
re-runs the pipeline on it (into `demo/raw/`) and compares the new numbers with the stored ones.
It reads `results/raw/`, `results/raw_agents/` and the clones in `work/repos/`; Python standard
library only.

```powershell
python -m explorer.prepare   # once: records where each lint problem is (same rules as the pipeline)
python -m explorer.server    # then open http://localhost:8479
```

## Results

* `results/metrics.csv`, `results/group_stats.csv`: every metric per repository; group medians,
  Mann–Whitney U, Cliff's δ, Holm-adjusted p (human vs. Claude Code)
* `results/agents/`: the same for all three groups, other agents vs. each group
* `results/final/`: paired Wilcoxon, pooled, size-adjusted tests, the power estimate and the
  sensitivity analyses (`sensitivity.csv`, `sensitivity_summary.csv`)
* `results/testability.csv`, `results/agents/testability.csv`: structural testability per project
* `results/top_rules.csv`, `results/tsc_codes.csv`: most frequent lint rules and compiler diagnostics
* `results/figures/`: figures used in the paper; `report/slides/`: figures used in the presentation
* `results/raw/<id>/`, `results/raw_agents/<id>/`: raw artefacts (lint/tsc/loc/jscpd/stryker JSON, test logs)

## Layout

```
bench/      Python orchestration (discover, screen, kind, select_repos, run, legacy_tests,
            testability, analyze, compare_agents, final_stats, sensitivity, classifier_sample,
            authorship)
tools/      pinned Node analysis toolchain + in-container stage scripts
docker/     benchmark image
dataset/    candidates, screening decisions, kinds, pairs, frozen datasets
results/    raw per-repository artefacts, metrics, statistics, figures
report/     paper and milestone report generators (every number is read from results/)
explorer/   local web app for browsing per-project results
```

Full StrykerJS JSON reports (`results/raw*/*/mutation-*.json`) are not committed because they
embed copies of the analysed projects' source; `stryker.json` in each folder keeps the scores.
