"""Tiny shared markup so the report has one source and two renderings.

**bold**, *italic*, `code`, and ~ (non-breaking space).  `to_rl` produces
reportlab paragraph XML, `to_tex` produces LaTeX.
"""
from __future__ import annotations

import re

_B = re.compile(r"\*\*(.+?)\*\*")
_I = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_C = re.compile(r"`(.+?)`")


def to_rl(s: str) -> str:
    codes: list[str] = []

    def keep(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    s = _C.sub(keep, s)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = _B.sub(r"<b>\1</b>", s)
    s = _I.sub(r"<i>\1</i>", s)
    s = s.replace("~", "&nbsp;").replace("--", "\u2013")
    for i, c in enumerate(codes):
        c = c.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        s = s.replace(f"\x00{i}\x00", f'<font face="Courier" size="8.6">{c}</font>')
    return s


_TEX_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
            "{": r"\{", "}": r"\}", "^": r"\^{}", "<": r"\textless{}", ">": r"\textgreater{}"}


def _esc(s: str) -> str:
    return "".join(_TEX_ESC.get(ch, ch) for ch in s)


def to_tex(s: str) -> str:
    codes: list[str] = []

    def keep(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    s = _C.sub(keep, s)
    s = s.replace("~", "\x01")
    s = _esc(s)
    s = _B.sub(r"\\textbf{\1}", s)
    s = _I.sub(r"\\emph{\1}", s)
    s = s.replace("\x01", "~").replace("\u2264", r"$\leq$").replace("\u2265", r"$\geq$").replace("\u00d7", r"$\times$")
    s = s.replace("\u2192", r"$\rightarrow$").replace("\u2013", "--").replace("\u2014", "---").replace("\u03b4", r"$\delta$")
    for i, c in enumerate(codes):
        s = s.replace(f"\x00{i}\x00", r"\texttt{" + _esc(c) + "}")
    return s
