"""Benchmark orchestrator.

For each repository in dataset/repos.csv:

  fetch      blobless clone, checkout the pinned commit (pre-2021 for the human
             group; the frozen HEAD SHA for the LLM group), record authorship
             evidence over the full history up to the pin
  inventory  classify .ts/.tsx files into production vs test code
  container  fresh `ts-llm-bench` container; repo copied in (host copy is read-only)
  install    dependency install with the project's own package manager & lockfile
  loc        size / comment metrics            (tools/loc.mjs)
  lint       ESLint + SonarJS + complexity     (tools/lint.mjs)
  dup        duplication with jscpd            (Sonar-like 100-token threshold)
  tsc        compilation with the project's own TypeScript + tsconfig
  test       the project's own test script
  mutate     StrykerJS on a seeded file sample (only when tests pass)

Every stage writes raw artefacts to results/raw/<repo_id>/ and the merged
record to results/raw/<repo_id>/summary.json.  Stages are resumable.

usage:  python -m bench.run [--only H01,L03] [--jobs 3] [--static-only] [--skip-mutation] [--force]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bench.authorship import local_history_share

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset" / "repos.csv"
REPOS = ROOT / "work" / "repos"
RAW = Path(os.environ.get("BENCH_RAW", ROOT / "results" / "raw"))  # override for demo / scratch runs
IMAGE = "ts-llm-bench:1"

EXCLUDED_DIRS = {"node_modules", "dist", "build", "out", "coverage", ".next", ".nuxt", ".git",
                 "vendor", ".stryker-tmp", "www", "platforms", ".turbo", ".cache", "storybook-static",
                 ".expo", "android", "ios", ".vercel", ".svelte-kit", "tmp", "temp", "generated"}
TEST_DIRS = {"test", "tests", "__tests__", "__mocks__", "e2e", "spec", "specs", "testing",
             "fixtures", "__fixtures__", "test-utils", "mocks", "cypress", "playwright"}
TEST_FILE = re.compile(r"\.(test|spec|e2e|stories|case|fixture|fixtures|mock|mocks)\.[cm]?tsx?$|(^|/)(setupTests|test-setup|jest\.setup|vitest\.setup)\.[cm]?tsx?$", re.I)
ROOT_TOOLING_DIRS = {"scripts", "tools", "bin", "config", "configs", "docs", "examples", "example", "benchmark", "benchmarks"}
SRC_FILE = re.compile(r"\.([cm]?ts|tsx)$")
CONFIG_FILE = re.compile(r"(^|/)[^/]*\.config\.[cm]?ts$|(^|/)(jest|vitest|vite|playwright|webpack|rollup|tsup|eslint)\.[^/]*\.[cm]?ts$")


def sh(cmd: list[str], timeout: int | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(cmd, 124, (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""),
                                           "TIMEOUT")


def log(rid: str, msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {rid}: {msg}", flush=True)


# --------------------------------------------------------------------------- host-side stages
def fetch(row: dict) -> dict:
    rid, name, pin = row["repo_id"], row["full_name"], row["pin"]
    dest = REPOS / rid
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = sh(["git", "-c", "core.autocrlf=false", "-c", "core.longpaths=true", "clone", "--filter=blob:none",
                "--no-checkout", f"https://github.com/{name}.git", str(dest)], timeout=900)
        if r.returncode != 0:
            raise RuntimeError(f"clone failed: {r.stderr[-400:]}")
    sh(["git", "-C", str(dest), "config", "core.autocrlf", "false"])
    sh(["git", "-C", str(dest), "config", "core.longpaths", "true"])
    r = sh(["git", "-C", str(dest), "checkout", "--force", "--detach", pin], timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"checkout {pin} failed: {r.stderr[-400:]}")
    sha = sh(["git", "-C", str(dest), "rev-parse", "HEAD"]).stdout.strip()
    date = sh(["git", "-C", str(dest), "show", "-s", "--format=%cI", "HEAD"]).stdout.strip()
    ai, total, agents = local_history_share(dest)
    first = sh(["git", "-C", str(dest), "log", "--reverse", "--format=%cI", "HEAD"]).stdout.split("\n", 1)[0].strip()
    return {"sha": sha, "commit_date": date, "first_commit_date": first, "commits_to_pin": total,
            "ai_commits_to_pin": ai, "ai_commit_share": round(ai / total, 4) if total else 0.0,
            "ai_agents": sorted(agents)}


def inventory(rid: str) -> dict:
    root = REPOS / rid
    prod, test, skipped = [], [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")]
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        parts = set(rel_dir.lower().split("/")) if rel_dir != "." else set()
        for fn in filenames:
            if not SRC_FILE.search(fn) or fn.endswith(".d.ts") or fn.endswith(".d.mts") or fn.endswith(".d.cts"):
                continue
            rel = fn if rel_dir == "." else f"{rel_dir}/{fn}"
            if rel_dir.split("/")[0].lower() in ROOT_TOOLING_DIRS:
                skipped += 1
                continue
            p = Path(dirpath) / fn
            size = p.stat().st_size
            if size > 400_000:  # bundles / generated blobs
                skipped += 1
                continue
            if TEST_FILE.search(rel) or parts & TEST_DIRS:
                test.append(rel)
            elif CONFIG_FILE.search(rel):
                skipped += 1
            else:
                prod.append(rel)
    pm = "npm"
    if (root / "pnpm-lock.yaml").exists():
        pm = "pnpm"
    elif (root / "yarn.lock").exists():
        pm = "yarn"
    lock = next((f for f in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "npm-shrinkwrap.json",
                             "bun.lock", "bun.lockb") if (root / f).exists()), "")
    return {"prod": sorted(prod), "test": sorted(test), "skipped": skipped, "pm": pm, "lockfile": lock,
            "yarn_berry": (root / ".yarnrc.yml").exists()}


# --------------------------------------------------------------------------- container stages
class Box:
    def __init__(self, rid: str, out: Path, cpus: str):
        self.rid, self.name = rid, f"tsb-{rid.lower()}"
        sh(["docker", "rm", "-f", self.name])
        src = str((REPOS / rid).resolve())
        r = sh(["docker", "run", "-d", "--name", self.name, f"--cpus={cpus}", "--memory=8g",
                "--mount", f"type=bind,source={src},target=/src,readonly",
                "--mount", f"type=bind,source={out.resolve()},target=/out",
                "--mount", "type=volume,source=tsb-npm-cache,target=/root/.npm",
                "--mount", "type=volume,source=tsb-pnpm-store,target=/root/.local/share/pnpm",
                "--mount", "type=volume,source=tsb-yarn-cache,target=/usr/local/share/.cache/yarn",
                IMAGE, "sleep", "infinity"])
        if r.returncode != 0:
            raise RuntimeError("docker run failed: " + r.stderr[-300:])
        self.exec("tar -C /src --exclude=./.git -cf - . | tar -C /work -xf -", 900)

    def exec(self, script: str, timeout: int) -> subprocess.CompletedProcess:
        return sh(["docker", "exec", "-w", "/work", self.name, "bash", "-lc", script], timeout=timeout)

    def close(self) -> None:
        sh(["docker", "rm", "-f", self.name])


def install_cmds(inv: dict) -> list[str]:
    pm, lock = inv["pm"], inv["lockfile"]
    if pm == "pnpm":
        base = ["corepack pnpm install --frozen-lockfile", "corepack pnpm install --no-frozen-lockfile"]
        return base + ["corepack pnpm install --no-frozen-lockfile --ignore-scripts"]
    if pm == "yarn":
        if inv["yarn_berry"]:
            return ["corepack yarn install --immutable", "corepack yarn install",
                    "YARN_ENABLE_SCRIPTS=0 corepack yarn install"]
        return ["corepack yarn install --frozen-lockfile --ignore-engines --network-timeout 600000",
                "corepack yarn install --ignore-engines --network-timeout 600000",
                "corepack yarn install --ignore-engines --ignore-scripts --network-timeout 600000"]
    first = "npm ci" if lock in ("package-lock.json", "npm-shrinkwrap.json") else "npm install"
    return [first, "npm install --legacy-peer-deps", "npm install --legacy-peer-deps --ignore-scripts"]


def stage_install(box: Box, inv: dict, out: Path, static_only: bool = False) -> dict:
    attempts = []
    cmds = install_cmds(inv)
    if static_only:  # no lifecycle scripts: no third-party code is executed
        cmds = list(dict.fromkeys(
            c if ("ignore-scripts" in c or "ENABLE_SCRIPTS=0" in c)
            else ("YARN_ENABLE_SCRIPTS=0 " + c if inv["yarn_berry"] else c + " --ignore-scripts")
            for c in cmds))
    for i, cmd in enumerate(cmds):
        if i:  # clean partial install before retrying
            box.exec("rm -rf node_modules", 600)
        t0 = time.time()
        r = box.exec(f"{cmd} > /out/install-{i}.log 2>&1", 1800)
        attempts.append({"cmd": cmd, "exit": r.returncode, "seconds": round(time.time() - t0, 1)})
        if r.returncode == 0:
            return {"ok": True, "level": i, "attempts": attempts}
    return {"ok": False, "level": None, "attempts": attempts}


def stage_node(box: Box, script: str, timeout: int) -> tuple[int, str]:
    r = box.exec(script, timeout)
    return r.returncode, (r.stdout + r.stderr)[-3000:]


def stage_test(box: Box, inv: dict) -> dict:
    cmd = {"npm": "npm test", "pnpm": "corepack pnpm test", "yarn": "corepack yarn test"}[inv["pm"]]
    t0 = time.time()
    r = box.exec(f"timeout 900 {cmd} > /out/test.log 2>&1", 960)
    return {"cmd": cmd, "exit": r.returncode, "passed": r.returncode == 0,
            "timed_out": r.returncode == 124, "seconds": round(time.time() - t0, 1)}


# --------------------------------------------------------------------------- driver
def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def bench_repo(row: dict, args) -> dict:
    rid = row["repo_id"]
    out = RAW / rid
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "summary.json"
    summary = {} if args.force else load(summary_path)
    summary.update({k: row[k] for k in ("repo_id", "group", "full_name", "stars", "created_at", "pin")})

    def save():
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    log(rid, f"fetch {row['full_name']} @ {row['pin'][:10]}")
    summary["fetch"] = fetch(row)
    inv = inventory(rid)
    (out / "files.json").write_text(json.dumps(inv), encoding="utf-8")
    summary["inventory"] = {"prod_files": len(inv["prod"]), "test_files": len(inv["test"]),
                            "skipped": inv["skipped"], "pm": inv["pm"], "lockfile": inv["lockfile"]}
    save()

    box = Box(rid, out, args.cpus)
    try:
        code, txt = stage_node(box, "node /tools/loc.mjs /out/files.json /out/loc.json", 900)
        summary["loc"] = load(out / "loc.json") or {"error": txt}
        log(rid, f"loc prod={summary['loc'].get('prod', {}).get('code')} test={summary['loc'].get('test', {}).get('code')}")

        code, txt = stage_node(box, "node /tools/lint.mjs /out/files.json /out/lint.json", 1800)
        summary["lint_ok"] = code == 0
        if code != 0:
            summary["lint_error"] = txt
        log(rid, f"lint exit={code}")

        code, txt = stage_node(box, "node -e \"const f=require('/out/files.json');require('fs').writeFileSync('/tmp/prod.txt',f.prod.join('\\n'))\" && "
                                    "xargs -a /tmp/prod.txt -d '\\n' node /tools/node_modules/jscpd/bin/jscpd --min-tokens 100 "
                                    "--min-lines 5 --mode strict --reporters json --output /out/jscpd --silent "
                                    "--format typescript,tsx --max-size 400kb", 1800)
        summary["dup_ok"] = (out / "jscpd" / "jscpd-report.json").exists()
        log(rid, f"dup ok={summary['dup_ok']}")
        save()

        log(rid, f"install ({inv['pm']}, lock={inv['lockfile'] or 'none'})")
        summary["install"] = stage_install(box, inv, out, args.static_only)
        summary["install"]["static_only"] = args.static_only
        log(rid, f"install ok={summary['install']['ok']} level={summary['install']['level']}")
        save()

        code, txt = stage_node(box, "node /tools/tscheck.mjs /out/tsc.json", 3600)
        summary["tsc"] = {k: v for k, v in load(out / "tsc.json").items() if k != "samples"} or {"error": txt}
        log(rid, f"tsc errors={summary['tsc'].get('errors_total')}")
        save()

        if args.static_only:
            log(rid, "static-only mode: tests and mutation testing not run")
            save()
            return summary
        summary["test"] = stage_test(box, inv) if summary["install"]["ok"] else {"passed": False, "skipped": "install failed"}
        log(rid, f"test passed={summary['test']['passed']}")
        save()

        if args.skip_mutation:
            summary.setdefault("mutation", {"status": "skipped"})
        elif summary["test"]["passed"]:
            log(rid, "mutation testing")
            env = f"MUTATE_CONCURRENCY={args.mutate_concurrency} MUTATE_TIME_LIMIT_MIN={args.mutate_minutes}"
            stage_node(box, f"{env} node /tools/mutate.mjs /out/files.json {inv['pm']} /out/stryker.json",
                       (args.mutate_minutes * 2 + 15) * 60)
            m = load(out / "stryker.json")
            summary["mutation"] = {k: v for k, v in m.items() if k not in ("attempts",)}
            summary["mutation"]["attempts"] = [{k: v for k, v in a.items() if k != "log_tail"} for a in m.get("attempts", [])]
            log(rid, f"mutation status={m.get('status')} score={m.get('mutation_score')}")
        else:
            summary["mutation"] = {"status": "tests-not-passing"}
        save()
    finally:
        box.close()
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--cpus", default="4")
    ap.add_argument("--mutate-concurrency", type=int, default=3)
    ap.add_argument("--mutate-minutes", type=int, default=20)
    ap.add_argument("--skip-mutation", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--static-only", action="store_true",
                    help="never execute repository code: install with scripts disabled, skip tests and mutation")
    args = ap.parse_args()

    rows = list(csv.DictReader(DATASET.open(encoding="utf-8")))
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r["repo_id"] in wanted]
    failures = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(bench_repo, r, args): r["repo_id"] for r in rows}
        for f in as_completed(futs):
            rid = futs[f]
            try:
                f.result()
                log(rid, "DONE")
            except Exception as e:  # keep going; record the failure
                failures[rid] = str(e)
                log(rid, f"FAILED {e}")
                (RAW / rid).mkdir(parents=True, exist_ok=True)
                (RAW / rid / "error.txt").write_text(str(e), encoding="utf-8")
    freeze_pins()
    print("failures:", failures or "none")


def freeze_pins() -> None:
    """Replace the symbolic 'HEAD' pins of the LLM group with the SHAs actually analysed."""
    rows = list(csv.DictReader(DATASET.open(encoding="utf-8")))
    changed = False
    for r in rows:
        s = load(RAW / r["repo_id"] / "summary.json")
        sha = s.get("fetch", {}).get("sha")
        if r["pin"] == "HEAD" and sha:
            r["pin"], r["pin_date"], changed = sha, s["fetch"]["commit_date"][:10], True
    if changed:
        with DATASET.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
