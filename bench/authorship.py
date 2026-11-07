"""Authorship evidence: detect commits attributed to an AI coding agent.

Coding agents leave machine-readable traces in commit metadata:
Claude Code appends "Co-Authored-By: Claude ..." and "Generated with
[Claude Code]"; Cursor, Copilot, Codex, Devin, Aider, OpenHands, Jules and
others use co-author trailers, bot authors or message prefixes.  The share of
such commits is our *positive* evidence of LLM authorship (a lower bound: an
agent can be used without leaving a trailer).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

AGENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "claude-code": re.compile(r"co-authored-by:\s*claude|generated with \[?claude code|claude\.(ai|com)/code", re.I),
    "cursor": re.compile(r"co-authored-by:\s*cursor|cursoragent@cursor\.com", re.I),
    "copilot": re.compile(r"co-authored-by:\s*copilot|copilot-swe-agent", re.I),
    "codex": re.compile(r"co-authored-by:\s*(openai\s*)?codex|chatgpt-codex-connector|codex@openai\.com", re.I),
    "devin": re.compile(r"devin-ai-integration|co-authored-by:\s*devin", re.I),
    "aider": re.compile(r"^aider:|co-authored-by:\s*aider", re.I | re.M),
    "openhands": re.compile(r"co-authored-by:\s*openhands|openhands@all-hands\.dev", re.I),
    "jules": re.compile(r"google-labs-jules|co-authored-by:\s*jules", re.I),
    "gemini": re.compile(r"co-authored-by:\s*gemini", re.I),
    "windsurf": re.compile(r"co-authored-by:\s*(windsurf|cascade)", re.I),
}
BOT_LOGINS = {"claude": "claude-code", "copilot": "copilot", "copilot-swe-agent": "copilot",
              "devin-ai-integration[bot]": "devin", "google-labs-jules[bot]": "jules",
              "cursor-agent": "cursor", "chatgpt-codex-connector[bot]": "codex"}


def classify(message: str, author_name: str = "", author_email: str = "", login: str = "") -> str | None:
    blob = f"{message}\n{author_name} <{author_email}>"
    for agent, pat in AGENT_PATTERNS.items():
        if pat.search(blob):
            return agent
    return BOT_LOGINS.get((login or "").lower())


def ai_commit_share(nodes: list[dict]) -> tuple[float, set[str]]:
    """nodes: GraphQL commit nodes with message + author{name,email,user{login}}."""
    if not nodes:
        return 0.0, set()
    agents: set[str] = set()
    hits = 0
    for n in nodes:
        a = n.get("author") or {}
        agent = classify(n.get("message", ""), a.get("name") or "", a.get("email") or "",
                         ((a.get("user") or {}).get("login")) or "")
        if agent:
            hits += 1
            agents.add(agent)
    return hits / len(nodes), agents


def local_history_share(repo: Path, rev: str = "HEAD") -> tuple[int, int, set[str]]:
    """Full-history version computed on a clone: (ai_commits, total_commits, agents)."""
    out = subprocess.run(["git", "-C", str(repo), "log", rev, "--format=%an%x1f%ae%x1f%B%x1e"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    total = hits = 0
    agents: set[str] = set()
    for rec in out.split("\x1e"):
        if not rec.strip():
            continue
        name, email, msg = (rec.strip("\n").split("\x1f") + ["", "", ""])[:3]
        total += 1
        agent = classify(msg, name, email)
        if agent:
            hits += 1
            agents.add(agent)
    return hits, total, agents
