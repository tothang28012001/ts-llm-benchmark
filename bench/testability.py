"""Structural testability (RQ2), from the static import graph of each project.

Instructor feedback on the proposal noted that RQ2 asks about *structural
testability* but no measure covered it.  Following Bruntink and van Deursen's
class-testability study (JSS 2006), which found that a unit's size and its
fan-out (the number of other units it depends on) predict how much test code it
needs, we measure, per repository and from source alone:

  fanout_mean        mean number of distinct *project* modules imported by a production file
                     (coupling; lower means units are easier to test in isolation)
  ext_fanout_mean    mean number of distinct external packages imported by a production file
  direct_test_pct    % of production code lines in files that some test file imports directly
                     (units that have their own test entry point)
  test_reach_pct     % of production code lines in files reachable from any test file through
                     the import graph (code the test suite can load at all)

Imports are read with a lexer-level regex (static `import`/`export ... from`,
`require()`, dynamic `import()`), relative specifiers and tsconfig `paths` /
`baseUrl` aliases are resolved, and ESM `.js` specifiers map back to `.ts` files.
Production and test files are the pipeline's own classification (files.json).

Output: results/testability.csv (and results/agents/testability.csv for raw_agents)
usage: python -m bench.testability
"""
from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPOS = ROOT / "work" / "repos"
SPEC = re.compile(r"""(?:\bimport\s+(?:type\s+)?(?:[\w*{}\s,$]+?\s+from\s+)?|\bexport\s+(?:type\s+)?[\w*{}\s,$]*?\s+from\s+|\brequire\s*\(\s*|\bimport\s*\(\s*)["']([^"'\n]+)["']""")
COMMENT = re.compile(r"/\*.*?\*/|(?<![:\"'\\])//[^\n]*", re.S)
EXTS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")


def loose_json(text: str) -> dict:
    """Parse tsconfig-style JSON: comments and trailing commas, ignoring comment markers inside strings."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    text = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def aliases(repo: Path) -> tuple[Path | None, list[tuple[str, list[str]]]]:
    cfg = loose_json((repo / "tsconfig.json").read_text(encoding="utf-8", errors="replace")) \
        if (repo / "tsconfig.json").exists() else {}
    ext = cfg.get("extends")
    if isinstance(ext, str) and ext.startswith(".") and (repo / ext).exists():
        base = loose_json((repo / ext).read_text(encoding="utf-8", errors="replace"))
        co = {**(base.get("compilerOptions") or {}), **(cfg.get("compilerOptions") or {})}
    else:
        co = cfg.get("compilerOptions") or {}
    base_url = repo / co["baseUrl"] if co.get("baseUrl") else None
    paths = [(k, v) for k, v in (co.get("paths") or {}).items() if isinstance(v, list)]
    return base_url, paths


def resolve(target: Path, known: dict[str, str], repo: Path) -> str | None:
    try:
        rel = target.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None
    stem = re.sub(r"\.(m|c)?jsx?$", "", rel)
    for c in (rel, *(stem + e for e in EXTS), *(f"{rel}/index{e}" for e in EXTS)):
        if c in known:
            return c
    return None


def analyse(rid: str, raw: Path) -> dict | None:
    repo, fj = REPOS / rid, raw / rid / "files.json"
    if not repo.exists() or not fj.exists():
        return None
    files = json.loads(fj.read_text(encoding="utf-8"))
    prod, test = set(files.get("prod", [])), set(files.get("test", []))
    if not prod:
        return None
    known = {f: f for f in prod | test}
    base_url, paths = aliases(repo)
    edges: dict[str, set[str]] = {}
    ext: dict[str, set[str]] = {}
    loc: dict[str, int] = {}
    for f in prod | test:
        try:
            src = (repo / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        loc[f] = sum(1 for line in src.splitlines() if line.strip())
        src = COMMENT.sub("", src)
        out, pkgs = set(), set()
        for spec in SPEC.findall(src):
            hit = None
            if spec.startswith("."):
                hit = resolve((repo / f).parent / spec, known, repo)
            else:
                for pat, targets in paths:
                    pre = pat.rstrip("*")
                    if spec == pat or (pat.endswith("*") and spec.startswith(pre)):
                        for t in targets:
                            root = base_url or (repo / "tsconfig.json").parent
                            hit = resolve(root / t.replace("*", spec[len(pre):]), known, repo)
                            if hit:
                                break
                    if hit:
                        break
                if not hit and base_url is not None:
                    hit = resolve(base_url / spec, known, repo)
                if not hit and not spec.startswith(("node:", "#")):
                    pkgs.add("/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0])
            if hit and hit != f:
                out.add(hit)
        edges[f], ext[f] = out, pkgs
    prod = {f for f in prod if f in loc}
    total = sum(loc[f] for f in prod) or 1
    direct = {g for t in test for g in edges.get(t, ()) if g in prod}
    seen, q = set(), deque(g for t in test for g in edges.get(t, ()))
    while q:
        g = q.popleft()
        if g in seen:
            continue
        seen.add(g)
        q.extend(edges.get(g, ()))
    reach = seen & prod
    return {"repo_id": rid,
            "fanout_mean": round(sum(len(edges[f] & prod) for f in prod) / len(prod), 3),
            "ext_fanout_mean": round(sum(len(ext[f]) for f in prod) / len(prod), 3),
            "direct_test_pct": round(100 * sum(loc[f] for f in direct) / total, 2),
            "test_reach_pct": round(100 * sum(loc[f] for f in reach) / total, 2),
            "n_prod_files": len(prod), "n_test_files": len(test)}


def main() -> None:
    for raw, out in ((ROOT / "results" / "raw", ROOT / "results" / "testability.csv"),
                     (ROOT / "results" / "raw_agents", ROOT / "results" / "agents" / "testability.csv")):
        rows = [r for d in sorted(raw.iterdir()) if d.is_dir() and (r := analyse(d.name, raw))]
        df = pd.DataFrame(rows)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        print(out.relative_to(ROOT), len(df))
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
