"""Project kind, used to match human and LLM projects by kind as well as size.

For every eligible repository in dataset/screened.csv and dataset/screened_trailers.csv
this fetches the root package.json (at the human pin commit, or HEAD for LLM
projects) with batched GraphQL queries and assigns one kind from fixed rules,
checked in this order:

  extension  VS Code / Obsidian / Raycast / browser extension or plugin
  ui-app     a private or entry-less package that depends on a UI framework
             (React DOM, Vue, Svelte, Angular, Solid, Preact, Electron, Tauri, React Native)
  service    depends on a server, bot or MCP framework (express, fastify, koa, hono,
             NestJS, the MCP SDK, discord.js, ...)
  cli        declares a "bin" entry
  library    everything else (a package meant to be imported)

Output: dataset/kinds.csv (full_name, kind, evidence)
usage: python -m bench.kind
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

from bench.screen import graphql

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dataset" / "kinds.csv"

UI = {"react-dom", "vue", "svelte", "@sveltejs/kit", "next", "nuxt", "@angular/core", "solid-js", "preact",
      "electron", "@tauri-apps/api", "react-native", "expo", "astro", "@remix-run/react", "react-router-dom"}
SERVICE = {"express", "fastify", "koa", "hono", "@nestjs/core", "@modelcontextprotocol/sdk", "discord.js",
           "telegraf", "grammy", "socket.io", "ws", "@hapi/hapi", "restify", "apollo-server", "@slack/bolt",
           "probot", "elysia"}
EXT = {"obsidian", "@raycast/api", "webextension-polyfill", "@types/chrome", "@types/vscode", "@figma/plugin-typings"}


def classify(pkg: dict) -> tuple[str, str]:
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {}),
            **(pkg.get("peerDependencies") or {})}
    runtime = {**(pkg.get("dependencies") or {})}
    names = set(deps)
    if (pkg.get("engines") or {}).get("vscode") or names & EXT:
        return "extension", ",".join(sorted(names & EXT)) or "engines.vscode"
    entry = any(k in pkg for k in ("main", "module", "exports", "types", "typings"))
    ui = names & UI
    if ui and (pkg.get("private") or not entry):
        return "ui-app", ",".join(sorted(ui))
    svc = set(runtime) & SERVICE
    if svc:
        return "service", ",".join(sorted(svc))
    if pkg.get("bin"):
        return "cli", "bin"
    return "library", "main/exports" if entry else "default"


def main() -> None:
    a = pd.read_csv(ROOT / "dataset" / "screened.csv")
    b = pd.read_csv(ROOT / "dataset" / "screened_trailers.csv")
    pool = pd.concat([a[a.eligible], b[b.eligible]]).drop_duplicates("full_name")
    rows = []
    items = list(pool.itertuples())
    for start in range(0, len(items), 20):
        chunk = items[start:start + 20]
        frags = []
        for i, r in enumerate(chunk):
            owner, name = r.full_name.split("/", 1)
            rev = r.pin_commit if r.group == "human" and isinstance(r.pin_commit, str) else "HEAD"
            frags.append(f'r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) '
                         f'{{ pkg: object(expression: {json.dumps(rev + ":package.json")}) {{ ... on Blob {{ text }} }} }}')
        data = graphql("query {" + "\n".join(frags) + "}")
        for i, r in enumerate(chunk):
            node = (data.get(f"r{i}") or {}).get("pkg") or {}
            try:
                pkg = json.loads(node.get("text") or "{}")
            except json.JSONDecodeError:
                pkg = {}
            kind, ev = classify(pkg) if pkg else ("unknown", "package.json not readable")
            rows.append({"full_name": r.full_name, "group": r.group, "kind": kind, "evidence": ev})
        print(f"{start + len(chunk)}/{len(items)}")
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["full_name", "group", "kind", "evidence"])
        w.writeheader()
        w.writerows(rows)
    print(pd.DataFrame(rows).groupby(["group", "kind"]).size().to_string())


if __name__ == "__main__":
    main()
