"""Local project explorer: browse the 24 benchmarked projects and re-run the pipeline.

Serves explorer/static/index.html and a small JSON API over the stored results
(results/raw), the cloned repositories (work/repos) and the lint locations
recorded by explorer/prepare.py.  A re-run writes to demo/raw, never over the
stored results.

usage: python -m explorer.server [--port 8479]      then open http://localhost:8479
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
RAW_AGENTS = ROOT / "results" / "raw_agents"  # the A01... "other agents" extension
DEMO = ROOT / "demo" / "raw"
REPOS = ROOT / "work" / "repos"
CACHE = ROOT / "explorer" / "cache"
STATIC = ROOT / "explorer" / "static"
RID = re.compile(r"^[HLA]\d\d$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# metrics shown on a project's overview: column, label, unit, lower_is_better, explanation
COMPARE = [
    ("lint_per_kloc", "Lint problems", "per 1,000 lines", True,
     "Rule violations ESLint finds (same rules for every project), scaled by code size."),
    ("cc_mean", "Branching per function", "avg cyclomatic complexity", True,
     "How many independent paths run through a typical function: if / else / loops / && all add one."),
    ("cognitive_mean", "How hard functions are to read", "avg cognitive complexity", True,
     "SonarSource's score for nesting and breaks in flow; higher means harder to follow."),
    ("any_per_kloc", "Uses of `any`", "per 1,000 lines", True,
     "Places where TypeScript's type checking is switched off by writing `any`."),
    ("dup_pct", "Copy-pasted code", "% of lines", True,
     "Share of lines that appear more than once (jscpd, blocks of 50+ tokens)."),
    ("comment_density", "Comments", "share of lines", False,
     "Comment lines divided by all non-blank lines."),
    ("test_to_code", "Test code per source line", "ratio", False,
     "Lines of test code for every line of production code."),
    ("tsc_errors_project", "Type errors", "in the project's own files", True,
     "Errors the TypeScript compiler reports in the project's own files (not in libraries)."),
    ("mutation_score", "Bugs the tests catch", "mutation score", False,
     "Share of deliberately planted small bugs that made at least one test fail."),
]

MUTANT_STATUS = {
    "Killed": "caught: a test failed",
    "Timeout": "caught: the tests hung",
    "Survived": "missed: every test still passed",
    "NoCoverage": "missed: no test runs this line",
    "CompileError": "not counted: the change did not compile",
    "RuntimeError": "not counted: the change crashed the runner",
    "Ignored": "not counted",
}


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def num(v):
    try:
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def raw(rid: str) -> Path:
    return (RAW_AGENTS if rid.startswith("A") else RAW) / rid


METRICS = {r["repo_id"]: r for r in csv.DictReader((ROOT / "results" / "metrics.csv").open(encoding="utf-8"))}
_AGENTS = ROOT / "results" / "agents" / "metrics.csv"  # written by `python -m bench.compare_agents`
if _AGENTS.exists():
    METRICS.update({r["repo_id"]: {**r, "group": "agent"} for r in csv.DictReader(_AGENTS.open(encoding="utf-8"))
                    if r["repo_id"].startswith("A")})


def medians() -> dict:
    out = {}
    for col, *_ in COMPARE:
        for g in ("human", "llm"):
            vals = [num(r[col]) for r in METRICS.values() if r["group"] == g and num(r[col]) is not None]
            out.setdefault(col, {})[g] = statistics.median(vals) if vals else None
    return out


MEDIANS = medians()


def mutation_report(raw: Path, s: dict):
    m = (s or {}).get("mutation") or {}
    if m.get("status") != "ok":
        return None
    runner, dtc, cov = m.get("runner"), m.get("disable_type_checks"), m.get("coverage_analysis")
    for name in (f"mutation-{runner}-{dtc}-{cov}.json", f"mutation-{runner}-{dtc}.json", f"mutation-{runner}.json"):
        if (raw / name).exists():
            return load(raw / name)
    found = sorted(raw.glob("mutation-*.json"), key=lambda p: p.stat().st_mtime)
    return load(found[-1]) if found else None


_reports: dict[str, dict | None] = {}


def report_for(rid: str):
    if rid not in _reports:
        _reports[rid] = mutation_report(raw(rid), load(raw(rid) / "summary.json"))
    return _reports[rid]


def lint_locations(rid: str) -> list:
    return load(CACHE / rid / "lint-locations.json") or []


# --------------------------------------------------------------------------- API
def api_projects():
    rows = []
    for rid, r in METRICS.items():
        rows.append({"id": rid, "group": r["group"], "name": r["full_name"], "stars": num(r["stars"]),
                     "kloc": num(r["prod_kloc"]), "lint": num(r["lint_per_kloc"]),
                     "tsc_clean": r["tsc_clean"] == "True", "tests": r["tests_passed"] == "True",
                     "mutation": num(r["mutation_score"])})
    return rows


def api_project(rid: str):
    s = load(raw(rid) / "summary.json") or {}
    r = METRICS[rid]
    files = load(raw(rid) / "files.json") or {"prod": [], "test": []}
    locs = lint_locations(rid)
    per_file: dict[str, int] = {}
    by_rule: dict[str, dict] = {}
    for v in locs:
        per_file[v["file"]] = per_file.get(v["file"], 0) + 1
        b = by_rule.setdefault(v["rule"], {"rule": v["rule"], "prod": 0, "test": 0, "example": v})
        b[v["kind"]] += 1
    rep = report_for(rid)
    mut_files = {}
    if rep:
        for f, d in rep["files"].items():
            c: dict[str, int] = {}
            for m in d["mutants"]:
                c[m["status"]] = c.get(m["status"], 0) + 1
            mut_files[f] = c
    jscpd = load(raw(rid) / "jscpd" / "jscpd-report.json") or {}
    dups = [{"lines": d["lines"], "a": d["firstFile"]["name"], "a_start": d["firstFile"]["start"],
             "a_end": d["firstFile"]["end"], "b": d["secondFile"]["name"], "b_start": d["secondFile"]["start"],
             "b_end": d["secondFile"]["end"]} for d in jscpd.get("duplicates", [])]
    compare = [{"col": c, "label": lab, "unit": unit, "lower_better": lb, "help": h, "value": num(r[c]),
                "human": MEDIANS[c]["human"], "llm": MEDIANS[c]["llm"]} for c, lab, unit, lb, h in COMPARE]
    logs = [p.name for p in sorted(raw(rid).glob("*.log"))]
    return {
        "id": rid, "group": r["group"], "name": r["full_name"], "stars": num(r["stars"]),
        "pin": s.get("pin"), "pin_date": r["pin_date"], "fetch": s.get("fetch"), "loc": s.get("loc"),
        "inventory": s.get("inventory"), "install": s.get("install"), "tsc": s.get("tsc"),
        "test": s.get("test"), "test_legacy": s.get("test_legacy"), "mutation": s.get("mutation"),
        "tests_counts": {"passed": num(r["tests_n_passed"]), "failed": num(r["tests_n_failed"])},
        "compare": compare, "files": {"prod": files["prod"], "test": files["test"]},
        "lint_per_file": per_file, "rules": sorted(by_rule.values(), key=lambda b: -(b["prod"] + b["test"])),
        "lint_total": len(locs), "mutation_files": mut_files, "duplicates": dups, "logs": logs,
        "tsc_samples": (load(raw(rid) / "tsc.json") or {}).get("samples", [])[:40],
    }


def api_file(rid: str, path: str):
    files = load(raw(rid) / "files.json") or {}
    if path not in set(files.get("prod", [])) | set(files.get("test", [])):
        raise PermissionError(path)
    rep = report_for(rid)
    mf = (rep or {}).get("files", {}).get(path)
    if mf:
        source = mf["source"]
    else:
        source = (REPOS / rid / path).read_text(encoding="utf-8", errors="replace")
    mutants = []
    for m in (mf or {}).get("mutants", []):
        st = m["status"]
        mutants.append({"line": m["location"]["start"]["line"], "col": m["location"]["start"]["column"],
                        "end_line": m["location"]["end"]["line"], "end_col": m["location"]["end"]["column"],
                        "mutator": m["mutatorName"], "replacement": m.get("replacement", ""), "status": st,
                        "meaning": MUTANT_STATUS.get(st, st)})
    return {"path": path, "kind": "prod" if path in files.get("prod", []) else "test", "source": source,
            "lint": [v for v in lint_locations(rid) if v["file"] == path], "mutants": mutants,
            "github": f"https://github.com/{METRICS[rid]['full_name']}/blob/{(load(raw(rid) / 'summary.json') or {}).get('pin')}/{path}"}


def api_log(rid: str, name: str, where: Path | None = None):
    if not re.fullmatch(r"[\w.-]+\.log", name):
        raise PermissionError(name)
    p = (where / rid if where else raw(rid)) / name
    txt = ANSI.sub("", p.read_text(encoding="utf-8", errors="replace"))
    return {"name": name, "text": txt[-60000:], "truncated": len(txt) > 60000}


# --------------------------------------------------------------------------- re-run
class Run:
    lock = threading.Lock()
    proc: subprocess.Popen | None = None
    rid: str | None = None
    lines: list[str] = []
    started = 0.0
    finished = 0.0
    exit: int | None = None
    mutation = False


def start_run(rid: str, mutation: bool, minutes: int):
    with Run.lock:
        if Run.proc and Run.proc.poll() is None:
            raise RuntimeError(f"{Run.rid} is still running")
        cmd = [sys.executable, "-u", "-m", "bench.run", "--only", rid, "--force", "--jobs", "1"]
        if rid.startswith("A"):
            cmd += ["--dataset", "dataset/repos_agents.csv"]
        cmd += ["--mutate-minutes", str(minutes)] if mutation else ["--skip-mutation"]
        env = {**os.environ, "BENCH_RAW": str(DEMO), "PYTHONIOENCODING": "utf-8"}
        DEMO.mkdir(parents=True, exist_ok=True)
        Run.lines = [f"$ BENCH_RAW=demo/raw python -m bench.run {' '.join(cmd[4:])}"]
        Run.rid, Run.exit, Run.started, Run.finished, Run.mutation = rid, None, time.time(), 0.0, mutation
        Run.proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=_pump, args=(Run.proc,), daemon=True).start()


def _pump(proc: subprocess.Popen):
    for line in proc.stdout:
        Run.lines.append(ANSI.sub("", line.rstrip("\n")))
    proc.wait()
    Run.exit, Run.finished = proc.returncode, time.time()


def stop_run():
    with Run.lock:
        if Run.proc and Run.proc.poll() is None:
            Run.proc.kill()
            subprocess.run(["docker", "rm", "-f", f"tsb-{Run.rid.lower()}"], capture_output=True)
            Run.lines.append("stopped by you; the container was removed")


def comparison(rid: str):
    old, new = load(raw(rid) / "summary.json") or {}, load(DEMO / rid / "summary.json") or {}
    lo, ln = load(raw(rid) / "lint.json") or {}, load(DEMO / rid / "lint.json") or {}

    def lint_total(l):
        return sum(l.get("violations", {}).get("prod", {}).values()) if l else None

    def cc(l):
        c = (l or {}).get("cyclomatic") or []
        return round(sum(c) / len(c), 3) if c else None

    def g(s, *ks):
        for k in ks:
            s = (s or {}).get(k)
        return s

    rows = [("Production code lines", g(old, "loc", "prod", "code"), g(new, "loc", "prod", "code")),
            ("Lint problems (production code)", lint_total(lo), lint_total(ln)),
            ("Functions analysed", (lo or {}).get("functions_prod"), (ln or {}).get("functions_prod")),
            ("Average cyclomatic complexity", cc(lo), cc(ln)),
            ("Install succeeded", g(old, "install", "ok"), g(new, "install", "ok")),
            ("Type errors (total)", g(old, "tsc", "errors_total"), g(new, "tsc", "errors_total")),
            ("Tests passed on Node 22", g(old, "test", "passed"), g(new, "test", "passed"))]
    if Run.mutation:
        rows += [("Mutation status", g(old, "mutation", "status"), g(new, "mutation", "status")),
                 ("Mutation score", g(old, "mutation", "mutation_score"), g(new, "mutation", "mutation_score"))]
    return [{"label": a, "stored": b, "now": c, "same": b == c} for a, b, c in rows]


def api_run_status(since: int):
    running = bool(Run.proc and Run.proc.poll() is None)
    out = {"rid": Run.rid, "running": running, "exit": Run.exit, "lines": Run.lines[since:], "next": len(Run.lines),
           "elapsed": round((Run.finished or time.time()) - Run.started, 1) if Run.started else 0}
    if Run.rid and not running and Run.exit is not None:
        out["compare"] = comparison(Run.rid)
    return out


# --------------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, default=str).encode("utf-8"))

    def route(self, method: str):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [p for p in u.path.split("/") if p]
        try:
            if method == "GET" and not parts:
                return self.send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if parts[:1] != ["api"]:
                return self.json({"error": "not found"}, 404)
            rid = parts[2] if len(parts) > 2 else None
            if rid is not None and not RID.match(rid) and parts[1] != "run":
                return self.json({"error": "bad project id"}, 400)
            if method == "GET":
                if parts[1:] == ["projects"]:
                    return self.json(api_projects())
                if parts[1] == "project" and rid:
                    return self.json(api_project(rid))
                if parts[1] == "file" and rid:
                    return self.json(api_file(rid, q.get("path", "")))
                if parts[1] == "log" and rid and len(parts) == 4:
                    return self.json(api_log(rid, parts[3]))
                if parts[1:] == ["run", "status"]:
                    return self.json(api_run_status(int(q.get("since", 0))))
            if method == "POST":
                if parts[1] == "run" and len(parts) == 3 and parts[2] == "stop":
                    stop_run()
                    return self.json({"ok": True})
                if parts[1] == "run" and rid and RID.match(rid):
                    start_run(rid, q.get("mutation") == "1", max(1, min(30, int(q.get("minutes", 5)))))
                    return self.json({"ok": True})
            return self.json({"error": "not found"}, 404)
        except PermissionError:
            return self.json({"error": "not a file of this project"}, 403)
        except FileNotFoundError:
            return self.json({"error": "file not found"}, 404)
        except RuntimeError as e:
            return self.json({"error": str(e)}, 409)

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8479)
    args = ap.parse_args()
    if not CACHE.exists():
        print("note: run `python -m explorer.prepare` once to see lint problems in the code view")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"explorer running at http://localhost:{args.port}  (Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        stop_run()


if __name__ == "__main__":
    main()
