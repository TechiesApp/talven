#!/usr/bin/env python3
"""Render benchmark comparison charts as light and dark SVGs for the docs.

Reads the JSON written by scripts/benchmark-languages.py and writes one
horizontal bar chart per metric into docs/assets/benchmarks/. Talven bars use
the brand indigo; other languages are neutral gray. Every bar is labeled with
its value, so identity and magnitude never depend on color alone.

Usage: python3 scripts/plot-benchmarks.py RESULTS.json [--out docs/assets/benchmarks]
"""
import argparse
import json
from pathlib import Path

import matplotlib
import matplotlib.ticker

matplotlib.use("svg")
import matplotlib.pyplot as plt  # noqa: E402

THEMES = {
    # Validated with the dataviz palette checker: lightness band, CVD separation, and 3:1 contrast.
    "light": {"talven": "#3B3BD9", "other": "#767C8A", "text": "#1F2328", "muted": "#59636E", "grid": "#D1D9E0"},
    "dark": {"talven": "#7272F2", "other": "#8C92A0", "text": "#E6EDF3", "muted": "#9198A1", "grid": "#3D444D"},
}
LANGUAGE = {"talven": "Talven", "c": "C", "rust": "Rust", "go": "Go", "java": "Java", "typescript": "TypeScript"}


def size_label(value):
    return f"{value / 1024 / 1024:.1f} MB" if value >= 1024 * 1024 else f"{value / 1024:.1f} KB"


def chart(rows, title, subtitle, path, theme, log=False, formatter=lambda v: f"{v:,.1f} ms"):
    colors = THEMES[theme]
    rows = sorted(rows, key=lambda row: row[1])
    labels = [row[0] for row in rows][::-1]
    values = [row[1] for row in rows][::-1]
    notes = [row[2] if len(row) > 2 else "" for row in rows][::-1]
    fig, ax = plt.subplots(figsize=(8, 0.46 * len(rows) + 1.25), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    bar_colors = [colors["talven"] if label.startswith("Talven") else colors["other"] for label in labels]
    bars = ax.barh(labels, values, height=0.56, color=bar_colors, linewidth=0)
    if log:
        ax.set_xscale("log")
    if formatter is size_label:
        ax.xaxis.set_major_locator(matplotlib.ticker.MultipleLocator(512 * 1024))
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
            lambda value, _: f"{value / 1024 / 1024:g} MB" if value else "0"))
    limit = max(values)
    ax.set_xlim(min(values) / 3 if log else 0, limit * (8 if log else 1.32))
    for bar, value, note in zip(bars, values, notes):
        text = formatter(value) + (f"  {note}" if note else "")
        ax.text(bar.get_width() * (1.08 if log else 1) + (0 if log else limit * 0.015),
                bar.get_y() + bar.get_height() / 2, text, va="center", fontsize=10, color=colors["text"])
    ax.tick_params(axis="y", length=0, labelsize=10.5, labelcolor=colors["text"])
    ax.tick_params(axis="x", colors=colors["muted"], labelsize=9)
    for label in ax.get_yticklabels():
        if label.get_text().startswith("Talven"):
            label.set_fontweight("bold")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(colors["grid"])
    ax.xaxis.grid(True, color=colors["grid"], linewidth=0.6)
    ax.set_axisbelow(True)
    fig.suptitle(title, x=0.01, y=0.985, ha="left", fontsize=13, fontweight="bold", color=colors["text"])
    ax.set_title(subtitle, loc="left", fontsize=9.5, color=colors["muted"], pad=8)
    fig.tight_layout()
    fig.savefig(path, format="svg", transparent=True, metadata={"Date": None})
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=Path)
    parser.add_argument("--out", type=Path, default=Path("docs/assets/benchmarks"))
    args = parser.parse_args()
    data = json.loads(args.results.read_text())["results"]
    args.out.mkdir(parents=True, exist_ok=True)
    charts = {
        "check": ([(label, row["median_ms"]) for label, row in data["check"].items()],
                  "Type-check or compile a 2,400-line program",
                  "Median wall-clock time, process start-up included. Lower is better."),
        "hello-time": ([(LANGUAGE[k], row["median_ms"]) for k, row in data["hello"].items()],
                       "Hello World: start to exit",
                       "Median wall-clock time to run the built program. Lower is better."),
        "fib": ([(LANGUAGE[k], row["median_ms"]) for k, row in data["fib"].items()],
                "Recursive fib(35)",
                "Median wall-clock time, default release settings. Talven checks every addition for overflow."),
    }
    for name, (rows, title, subtitle) in charts.items():
        for theme in THEMES:
            chart(rows, title, subtitle, args.out / f"{name}-{theme}.svg", theme)
    # Only self-contained executables are comparable: Java and TypeScript ship
    # small files but need a separately installed runtime to run.
    sizes = [(LANGUAGE[k], row["artifact_bytes"]) for k, row in data["hello"].items()
             if row["runtime_required"].startswith("none")]
    for theme in THEMES:
        chart(sizes, "Hello World: self-contained executable size",
              "Default release build, unstripped. Java and TypeScript are omitted: they need a runtime installed.",
              args.out / f"hello-size-{theme}.svg", theme, formatter=size_label)


if __name__ == "__main__":
    main()
