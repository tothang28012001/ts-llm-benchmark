# ts-llm-benchmark

An automated, containerised benchmark that compares **human-written** and **LLM-agent-generated**
TypeScript projects on compilation, code quality, maintainability and test effectiveness.

CMPT 479 D100 course project (Simon Fraser University). Authors: Simon Xie, Sukhdip Kandola, Thang To.
Licensed under MIT (see `LICENSE`). Milestone report: [`report/CMPT479 - Milestone Progress Report.pdf`](report/CMPT479%20-%20Milestone%20Progress%20Report.pdf).

## Research questions

1. How does code quality differ between human-written and LLM-generated TypeScript projects?
2. How do complexity, maintainability and structural testability differ?
3. Do LLM-generated projects have more compilation errors?

## Pipeline

```
discover ──► screen ──► select ──► run (per repo, fresh Docker container) ──► analyze
GitHub       GraphQL     size-       fetch → inventory → loc → lint → dup →     stats +
search       filters     matched     install → tsc → test → mutate              figures
```

| Stage | Tool | Output |
|---|---|---|
| Discovery | GitHub search API (`bench/discover.py`) | `dataset/candidates.csv` |
| Screening | GitHub GraphQL: package.json, tsconfig, test runner, TS size, AI-commit share, pre-2021 pin (`bench/screen.py`) | `dataset/screened.csv` |
| Selection | Most-starred eligible LLM repos + nearest-size human match (`bench/select_repos.py`) | `dataset/repos.csv` |
| Authorship | AI-agent commit trailers over the full history (`bench/authorship.py`) | `summary.json → fetch` |
| Size / comments | TypeScript parser (`tools/loc.mjs`) | `loc.json` |
| Code quality | ESLint 9 + typescript-eslint + SonarJS rules, identical config, inline disables ignored (`tools/lint.mjs`) | `lint.json` |
| Complexity | ESLint `complexity` (cyclomatic) and `sonarjs/cognitive-complexity`, per function | `lint.json` |
| Duplication | jscpd, 100-token / 5-line threshold | `jscpd/jscpd-report.json` |
| Compilation | the project's own `tsc` + `tsconfig.json` (`tools/tscheck.mjs`) | `tsc.json` |
| Tests | the project's own `test` script | `test.log` |
| Test effectiveness | StrykerJS 10 on a seeded 400-line file sample (`tools/mutate.mjs`) | `stryker.json` |

Every repository is analysed in a fresh container built from `docker/Dockerfile`. The host
checkout is mounted read-only, and the container is deleted afterwards.

## Reproducing

Requirements: Python 3.11 (`pip install -r requirements.txt`), Node 22+, Docker, and an
authenticated `gh` CLI (only needed for discovery and screening).

```bash
cd tools && npm ci && cd ..
docker build -t ts-llm-bench:1 -f docker/Dockerfile .

# optional: rebuild the dataset from scratch (dataset/*.csv is committed)
GH_TOKEN=$(gh auth token) python -m bench.discover
GH_TOKEN=$(gh auth token) python -m bench.screen
python -m bench.select_repos

# static stages only: no repository code is executed
python -m bench.run --static-only --jobs 3
# all stages, including the projects' tests and mutation testing (executes repository code in Docker)
python -m bench.run --jobs 3 --force
python -m bench.legacy_tests          # failing suites again, on a Node version from the project's era
python -m bench.analyze
python -m report.content              # rebuild the report
```

## Dataset

`dataset/repos.csv` freezes the 24 repositories (12 per group) and the exact commit each was analysed at.

* **Human group:** created between 2016 and mid-2020, last pushed before 2022, and pinned to the last
  commit before **2021-01-01**. That is before GitHub Copilot's preview (June 2021) and ChatGPT
  (Nov 2022), so the analysed code cannot be LLM-generated.
* **LLM group:** created in 2025 or later. At least 50% of the latest 100 commits must carry an
  AI-agent attribution trailer (e.g. `Co-Authored-By: Claude`). The full-history share is
  recomputed at the pin.

## Results and report

* `results/metrics.csv`: every derived metric, one row per repository
* `results/group_stats.csv`: group medians, Mann–Whitney U, Cliff's δ, Holm-adjusted p
* `results/top_rules.csv`, `results/tsc_codes.csv`: most frequent lint rules and compiler diagnostics
* `results/figures/`: figures used in the report
* `results/raw/<id>/`: raw artefacts (lint/tsc/loc/jscpd/stryker JSON, install and test logs)
* `dataset/test_failure_causes.csv`: manual diagnosis of every failing test suite

`python -m report.content` regenerates the milestone report from these files, as both
`report/CMPT479 - Milestone Progress Report.pdf` and `report/milestone.tex` (IEEEtran, for Overleaf).

## Layout

```
bench/      Python orchestration (discover, screen, select_repos, run, analyze, authorship)
tools/      pinned Node analysis toolchain + in-container stage scripts
docker/     benchmark image
dataset/    candidates, screening decisions, final frozen dataset
results/    raw per-repository artefacts, metrics.csv, group_stats.csv, figures/
```

Full StrykerJS JSON reports (`results/raw/*/mutation-*.json`, ~56 MB) are not committed because they
embed copies of the analysed projects' source; `stryker.json` in each folder keeps the scores.
