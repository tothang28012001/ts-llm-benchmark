"""Builds the milestone / progress report from the benchmark results.

Every number in the report is read from results/ and dataset/, so re-running
the pipeline and this script regenerates a consistent report.

Outputs
  report/CMPT479 - Milestone Progress Report.pdf   (IEEE-style two-column PDF)
  report/milestone.tex                             (same content, IEEEtran, for Overleaf / final paper)

usage: python -m report.content   (layout helpers live here; the text is in report/content.py)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from report.ieee_pdf import COL_W, Doc
from report.markup import to_rl, to_tex

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
OUT_DIR = ROOT / "report"
PDF_NAME = "CMPT479 - Milestone Progress Report.pdf"

TITLE = "Benchmarking Human-Written and LLM-Generated TypeScript Projects: Milestone Progress Report"
AUTHORS = "Simon Xie, Sukhdip Kandola, Thang To"
AFFIL = "CMPT 479 D100, School of Computing Science, Simon Fraser University, Burnaby, BC, Canada"

REFS = [
    "T. Tang, S. Alimadadi, and N. Sumner, \u201cFrom logic to toolchains: An empirical study of bugs in the TypeScript ecosystem,\u201d in *Proc. 23rd Int. Conf. Mining Software Repositories (MSR)*, ACM, 2026, pp. 539\u2013549.",
    "A. S. Molison, M. Moraes, G. Melo, F. Santos, and W. K. G. Assun\u00e7\u00e3o, \u201cIs LLM-generated code more maintainable and reliable than human-written code?\u201d in *Proc. ACM/IEEE Int. Symp. Empirical Software Engineering and Measurement (ESEM)*, 2025, pp. 151\u2013162.",
    "S. A. Licorish, A. Bajpai, C. Arora, F. Wang, and K. Tantithamthavorn, \u201cComparing human and LLM generated code: The jury is still out!\u201d arXiv:2501.16857, 2025.",
    "D. Cotroneo, C. Improta, and P. Liguori, \u201cHuman-written vs. AI-generated code: A large-scale study of defects, vulnerabilities, and complexity,\u201d in *Proc. 36th IEEE Int. Symp. Software Reliability Engineering (ISSRE)*, 2025, pp. 252\u2013263.",
    "A. Romazanov, G. Fraser, and S. Herbold, \u201cCDBench: Benchmarking the mutation testing capabilities of LLMs with Code Defenders,\u201d *Empirical Software Engineering*, vol. 31, no. 6, art. 166, 2026.",
    "S. Garg, B. Steenhoek, and Y. Huang, \u201cRescuing SWE-bench: A benchmark mutation approach for realistic agent evaluation,\u201d in *Proc. 5th ACM/IEEE Int. Conf. AI Engineering (CAIN)*, 2026.",
    "F. Tip, J. Bell, and M. Sch\u00e4fer, \u201cLLMorpheus: Mutation testing using large language models,\u201d *IEEE Trans. Software Engineering*, vol. 51, no. 6, pp. 1645\u20131665, 2025.",
    "T. J. McCabe, \u201cA complexity measure,\u201d *IEEE Trans. Software Engineering*, vol. SE-2, no. 4, pp. 308\u2013320, 1976.",
    "G. A. Campbell, \u201cCognitive complexity: An overview and evaluation,\u201d in *Proc. Int. Conf. Technical Debt (TechDebt)*, 2018, pp. 57\u201358.",
    "J. Romano, J. D. Kromrey, J. Coraggio, and J. Skowronek, \u201cAppropriate statistics for ordinal level data,\u201d in *Proc. Annual Meeting of the Florida Association of Institutional Research*, 2006.",
    "S. Holm, \u201cA simple sequentially rejective multiple test procedure,\u201d *Scandinavian J. Statistics*, vol. 6, no. 2, pp. 65\u201370, 1979.",
    "StrykerJS mutation testing framework, https://stryker-mutator.io; ESLint, https://eslint.org; typescript-eslint, https://typescript-eslint.io; SonarJS (eslint-plugin-sonarjs), https://github.com/SonarSource/SonarJS; jscpd, https://github.com/kucherenko/jscpd.",
]


# --------------------------------------------------------------------------- data
def load_all() -> dict:
    m = pd.read_csv(RES / "metrics.csv")
    gs = pd.read_csv(RES / "group_stats.csv").set_index("column")
    tsc_clean = json.loads((RES / "tsc_clean.json").read_text())
    top = pd.read_csv(RES / "top_rules.csv")
    codes = pd.read_csv(RES / "tsc_codes.csv")
    scr = pd.read_csv(ROOT / "dataset" / "screened.csv")
    cand = pd.read_csv(ROOT / "dataset" / "candidates.csv")
    summaries = {p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted((RES / "raw").glob("*/summary.json"))}
    return dict(m=m, gs=gs, tsc_clean=tsc_clean, top=top, codes=codes, scr=scr, cand=cand, s=summaries)


def fmt(x, nd=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "--"
    return f"{x:.{nd}f}"


def pval(p):
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "--"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


# --------------------------------------------------------------------------- renderer
class Out:
    """Writes the same content to the PDF and to LaTeX."""

    def __init__(self, pdf_path: Path):
        self.pdf = Doc(str(pdf_path), TITLE, AUTHORS)
        self.tex: list[str] = []
        self.fig_n = 0
        self.tab_n = 0

    def header(self):
        self.pdf.header(TITLE, AUTHORS, AFFIL)

    def abstract(self, text, kw):
        self.pdf.abstract(to_rl(text), to_rl(kw))
        self.tex += [r"\begin{abstract}", to_tex(text), r"\end{abstract}", r"\begin{IEEEkeywords}", to_tex(kw),
                     r"\end{IEEEkeywords}", ""]

    def h1(self, t):
        self.pdf.h1(t)
        self.tex.append(f"\\section{{{to_tex(t)}}}")

    def h2(self, t):
        self.pdf.h2(to_rl(t))
        self.tex.append(f"\\subsection{{{to_tex(t)}}}")

    def p(self, t, indent=True):
        self.pdf.p(to_rl(t), indent)
        self.tex += [("" if indent else r"\noindent ") + to_tex(t), ""]

    def bullets(self, items):
        self.pdf.bullets([to_rl(i) for i in items])
        self.tex += [r"\begin{itemize}"] + [r"\item " + to_tex(i) for i in items] + [r"\end{itemize}", ""]

    def figure(self, path: Path, caption: str, label: str):
        self.fig_n += 1
        dest = OUT_DIR / "figures" / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, dest)
        self.pdf.figure(str(path), to_rl(f"Fig.~{self.fig_n}. {caption}"))
        self.tex += [r"\begin{figure}[t]", r"\centering", f"\\includegraphics[width=\\columnwidth]{{figures/{path.name}}}",
                     f"\\caption{{{to_tex(caption)}}}", f"\\label{{{label}}}", r"\end{figure}", ""]

    def table(self, caption: str, rows: list[list[str]], widths_in: list[float], label: str, bold_rows=()):
        self.tab_n += 1
        roman = ["I", "II", "III", "IV", "V", "VI", "VII"][self.tab_n - 1]
        total = sum(widths_in)
        widths = [w / total * COL_W for w in widths_in]
        self.pdf.table(to_rl(f"TABLE {roman}<br/>{caption.upper()}").replace("&lt;br/&gt;", "<br/>"),
                       [[to_rl(c) for c in r] for r in rows], widths, bold_rows=bold_rows)
        spec = "l" + "c" * (len(rows[0]) - 1)
        body = [" & ".join(to_tex(c) for c in r) + r" \\" for r in rows]
        self.tex += [r"\begin{table}[t]", r"\caption{" + to_tex(caption) + "}", f"\\label{{{label}}}", r"\centering",
                     r"\scriptsize", r"\setlength{\tabcolsep}{2.5pt}", f"\\begin{{tabular}}{{{spec}}}", r"\toprule",
                     body[0], r"\midrule", *body[1:], r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]

    def refs(self):
        self.pdf.references([to_rl(r) for r in REFS])
        self.tex += [r"\begin{thebibliography}{99}"] + [f"\\bibitem{{r{i}}} " + to_tex(r) for i, r in enumerate(REFS, 1)] + [r"\end{thebibliography}"]

    def save(self):
        self.pdf.build()
        pre = [r"\documentclass[10pt,conference]{IEEEtran}", r"\usepackage{graphicx,booktabs,url}",
               r"\usepackage[T1]{fontenc}", r"\usepackage[utf8]{inputenc}", r"\begin{document}",
               f"\\title{{{to_tex(TITLE)}}}",
               r"\author{\IEEEauthorblockN{" + to_tex(AUTHORS) + r"}\IEEEauthorblockA{" + to_tex(AFFIL) + "}}",
               r"\maketitle", ""]
        (OUT_DIR / "milestone.tex").write_text("\n".join(pre + self.tex + [r"\end{document}", ""]), encoding="utf-8")
