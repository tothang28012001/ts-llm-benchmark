"""Era-matched test re-run (fairness control for the test-runnability metric).

A project pinned in 2017 was written for Node 8, not Node 22.  When a project's
test suite fails in the main (Node 22) container, this stage re-runs install +
tests in an official Node image contemporary with the pinned commit (or the
version named by .nvmrc / engines.node).  It separates *broken tests* from
*environment drift* (e.g. node-sass binaries that no longer build).

Mutation testing still requires Node >= 20 (StrykerJS 10), so it is not
repeated here.

usage: python -m bench.legacy_tests [--only H02,H05]
"""
from __future__ import annotations

import argparse
import json
import re
import time

from bench.run import RAW, REPOS, load, log, sh

ERA_NODE = [("2018-01-01", "8"), ("2019-01-01", "10"), ("2020-01-01", "12"), ("2099-01-01", "14")]


def node_for(rid: str, pin_date: str) -> tuple[str, str]:
    root = REPOS / rid
    nvmrc = root / ".nvmrc"
    if nvmrc.exists():
        m = re.search(r"(\d+)", nvmrc.read_text(encoding="utf-8", errors="replace"))
        if m and 6 <= int(m.group(1)) <= 22:
            return m.group(1), ".nvmrc"
    try:
        eng = (json.loads((root / "package.json").read_text(encoding="utf-8")).get("engines") or {}).get("node", "")
        m = re.search(r"(\d+)", eng)
        if m and 8 <= int(m.group(1)) <= 22 and not eng.strip().startswith(">"):
            return m.group(1), "engines.node"
    except (OSError, json.JSONDecodeError):
        pass
    return next(v for cutoff, v in ERA_NODE if pin_date < cutoff), "pin-date era"


def run(rid: str) -> dict:
    s = load(RAW / rid / "summary.json")
    inv = load(RAW / rid / "files.json")
    version, why = node_for(rid, s["fetch"]["commit_date"][:10])
    name = f"tsb-legacy-{rid.lower()}"
    sh(["docker", "rm", "-f", name])
    src = str((REPOS / rid).resolve())
    out = (RAW / rid).resolve()
    r = sh(["docker", "run", "-d", "--name", name, "--cpus=4", "--memory=8g", "-e", "CI=true",
            "-e", "PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=1", "-e", "CYPRESS_INSTALL_BINARY=0",
            "-e", "ELECTRON_SKIP_BINARY_DOWNLOAD=1", "-e", "HUSKY=0",
            "--mount", f"type=bind,source={src},target=/src,readonly",
            "--mount", f"type=bind,source={out},target=/out", "-w", "/work",
            f"node:{version}", "sleep", "infinity"], timeout=900)
    if r.returncode != 0:
        return {"node": version, "why": why, "status": "image-failed", "error": r.stderr[-300:]}
    ex = lambda cmd, t: sh(["docker", "exec", "-w", "/work", name, "bash", "-lc", cmd], timeout=t)
    try:
        ex("mkdir -p /work && tar -C /src --exclude=./.git -cf - . | tar -C /work -xf - && "
           "git config --global url.'https://github.com/'.insteadOf 'ssh://git@github.com/' && "
           "git config --global --add url.'https://github.com/'.insteadOf 'git@github.com:'", 900)
        if inv["pm"] == "yarn":
            cmds = ["yarn install --frozen-lockfile --ignore-engines", "yarn install --ignore-engines"]
            test = "yarn test"
        else:
            cmds = (["npm ci"] if inv["lockfile"] == "package-lock.json" else []) + ["npm install", "npm install --ignore-scripts"]
            test = "npm test"
        installed = None
        for i, c in enumerate(cmds):
            if ex(f"{c} > /out/legacy-install-{i}.log 2>&1", 1800).returncode == 0:
                installed = c
                break
            ex("rm -rf node_modules", 600)
        if not installed:
            return {"node": version, "why": why, "status": "install-failed"}
        t0 = time.time()
        r = ex(f"timeout 900 {test} > /out/legacy-test.log 2>&1", 960)
        return {"node": version, "why": why, "status": "ok", "install": installed,
                "passed": r.returncode == 0, "exit": r.returncode, "seconds": round(time.time() - t0, 1)}
    finally:
        sh(["docker", "rm", "-f", name])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    for d in sorted(RAW.iterdir()):
        s = load(d / "summary.json")
        if not s or (args.only and d.name not in args.only.split(",")):
            continue
        if not args.only and (s.get("test", {}).get("passed") or s.get("group") != "human"):
            continue  # LLM projects are contemporary with Node 22, so there is no older era to match
        log(d.name, "era-matched test re-run")
        res = run(d.name)
        s["test_legacy"] = res
        (d / "summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
        log(d.name, f"node {res['node']} ({res['why']}): {res.get('status')} passed={res.get('passed')}")


if __name__ == "__main__":
    main()
