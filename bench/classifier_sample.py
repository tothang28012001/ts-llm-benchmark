"""Manual validation of the production / test file classifier (bench.run.inventory).

Draws a seeded random sample of 100 classified files from the human and Claude Code projects
(30 production + 20 test files per group) and writes it to dataset/classifier_validation.csv.
Each file was then opened and judged by hand; the verdicts are stored in that CSV (column
`verdict`: correct / misclassified, with a note). Re-running this script with --draw prints the
same sample, so the review can be repeated. H18, H19 and H27 were being re-measured when the
sample was drawn and are not in the pool.

It also reports how much production code falls in the file types the review found misclassified
(Storybook stories and Cucumber step definitions), per group.

usage:  python -m bench.classifier_sample [--draw]
"""
from __future__ import annotations

import csv
import glob
import json
import os
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dataset" / "classifier_validation.csv"
NOT_PROD = re.compile(r"\.(stories|story)\.tsx?$|\.steps\.ts$|(^|/)(stories|storybook|step_definitions|steps)/")


def pool():
    p = {("human", "prod"): [], ("human", "test"): [], ("llm", "prod"): [], ("llm", "test"): []}
    for d in sorted(glob.glob(str(ROOT / "results" / "raw" / "*"))):
        rid = os.path.basename(d)
        if rid in ("H18", "H19", "H27"):
            continue
        f = json.load(open(os.path.join(d, "files.json"), encoding="utf-8"))
        g = "human" if rid[0] == "H" else "llm"
        for k in ("prod", "test"):
            p[(g, k)] += [(rid, x) for x in f[k]]
    return p


def draw():
    rng, p = random.Random(479), pool()
    want = {("human", "prod"): 30, ("llm", "prod"): 30, ("human", "test"): 20, ("llm", "test"): 20}
    return [(g, k, rid, path) for (g, k), n in want.items() for rid, path in rng.sample(p[(g, k)], n)]


def misplaced_share():
    out = {}
    for g in ("H", "L"):
        hit = tot = 0
        for d in glob.glob(str(ROOT / "results" / "raw" / f"{g}*")):
            prod = json.load(open(os.path.join(d, "files.json"), encoding="utf-8"))["prod"]
            hit += sum(bool(NOT_PROD.search(x)) for x in prod)
            tot += len(prod)
        out["human" if g == "H" else "llm"] = (hit, tot)
    return out


def main() -> None:
    if "--draw" in sys.argv:
        for row in draw():
            print(*row, sep="\t")
        return
    rows = list(csv.DictReader(OUT.open(encoding="utf-8")))
    ok = sum(r["verdict"] == "correct" for r in rows)
    print(f"{ok}/{len(rows)} correct")
    for r in rows:
        if r["verdict"] != "correct":
            print(" ", r["repo_id"], r["path"], "-", r["note"])
    for g, (hit, tot) in misplaced_share().items():
        print(f"{g}: {hit}/{tot} production files are stories or step definitions ({100 * hit / tot:.1f}%)")


if __name__ == "__main__":
    main()
