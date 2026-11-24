"""Large-type figures for the final presentation (16:9 slides).

Each figure is two strip plots (human / Claude Code / other agents) with medians,
drawn on the deck's light background.  Output: report/slides/*.png
usage: python -m report.slide_figs   (after bench.compare_agents)
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "report" / "slides"
BG, INK, MUTED, GRID = "#F7F6F2", "#14213D", "#5B6475", "#E2E0D8"
COLORS = {"human": "#2A78D6", "claude": "#EB6834", "other": "#1BAF7A"}
NAMES = {"human": "Human", "claude": "Claude Code", "other": "Other agents"}

FIGS = {
    "quality": [("lint_per_kloc", "Lint violations per KLOC", "log"), ("any_per_kloc", "Explicit any per KLOC (0 drawn at floor)", "log")],
    "complexity": [("cc_mean", "Mean cyclomatic complexity", "linear"), ("cc_over10_pct", "Functions with CC > 10 (%)", "linear")],
    "testability": [("direct_test_pct", "Code imported directly by tests (%)", "linear"),
                    ("test_reach_pct", "Code reachable from tests (%)", "linear")],
}


def main() -> None:
    df = pd.read_csv(ROOT / "results" / "agents" / "metrics.csv")
    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 15, "axes.edgecolor": MUTED,
                         "axes.linewidth": 1.0, "xtick.color": INK, "ytick.color": MUTED, "text.color": INK})
    rng = np.random.default_rng(479)
    for name, panels in FIGS.items():
        fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.6), facecolor=BG)
        for ax, (col, title, scale) in zip(axes, panels):
            ax.set_facecolor(BG)
            for i, g in enumerate(["human", "claude", "other"]):
                v = df.loc[df.stratum == g, col].dropna().astype(float).values
                true_med = float(np.median(v)) if len(v) else np.nan
                if scale == "log":
                    v = np.maximum(v, 0.3)   # zeros sit on the axis floor
                ax.scatter(i + rng.uniform(-0.17, 0.17, len(v)), v, s=70, color=COLORS[g], edgecolor=BG,
                           linewidth=1.2, zorder=3, alpha=0.95)
                if len(v):
                    mdn = float(np.median(v))
                    ax.hlines(mdn, i - 0.32, i + 0.32, color=INK, linewidth=3.2, zorder=4)
                    lab = f"{true_med:.1f}" if true_med < 100 else f"{true_med:.0f}"
                    ax.annotate(lab, (i + 0.36, max(mdn, 0.3) if scale == "log" else mdn), va="center",
                                fontsize=14, color=INK, fontweight="bold")
            ax.set_xticks(range(3), [NAMES[g] for g in ["human", "claude", "other"]])
            ax.set_xlim(-0.6, 2.75)
            ax.set_title(title, loc="left", fontsize=17, fontweight="bold", color=INK, pad=12)
            ax.tick_params(length=0, labelsize=14)
            ax.grid(axis="y", color=GRID, linewidth=1)
            ax.set_axisbelow(True)
            for sp in ("top", "right", "left"):
                ax.spines[sp].set_visible(False)
            if scale == "log":
                ax.set_yscale("log")
                ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{y:g}"))
        fig.tight_layout(pad=1.0, w_pad=3)
        fig.savefig(OUT / f"{name}.png", dpi=150, facecolor=BG)
        plt.close(fig)
        print("wrote", OUT / f"{name}.png")


if __name__ == "__main__":
    main()
