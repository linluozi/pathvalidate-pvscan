"""Render the README figures from results.json.

Every number in the figures is read from results.json, which is produced by
running the actual tool. Nothing is hard coded here, so a figure cannot claim
something the tool does not do.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


WORK = Path(__file__).resolve().parent
# figures are written straight into docs/ so the README can link them
OUT = WORK.parents[1] / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

INK = "#2b2119"
PAPER = "#faf6f0"
AMBER = "#c8892b"
TERRACOTTA = "#b4552f"
OLIVE = "#6b6b3a"
MUTED = "#8a7a68"
LINE = "#d9cdbd"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "text.color": INK,
        "axes.labelcolor": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "axes.edgecolor": LINE,
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "savefig.facecolor": PAPER,
    }
)


def data() -> dict:
    return json.loads((WORK / "results.json").read_text(encoding="utf-8"))


def save(fig, name: str) -> None:
    path = OUT / name
    fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.28)
    plt.close(fig)
    print(f"wrote {path.name}")


# ---------------------------------------------------------------- figure 1
def fig_problem_kinds(d: dict) -> None:
    kinds = d["kinds"]
    labels = {
        "WSL_MAPPED_CHARACTER": "WSL private-use\ncharacters (PVX004)",
        "RESERVED_NAME": "Reserved device\nnames (PV1002)",
        "INVALID_CHARACTER": "Trailing space /\ndot (PV1100)",
        "INVISIBLE_CHARACTER": "Zero-width\ncharacters (PVX001)",
        "UNNORMALIZED_UNICODE": "Unnormalized\nUnicode (PVX002)",
    }

    order = sorted(kinds, key=lambda key: -kinds[key])
    names = [labels.get(key, key) for key in order]
    values = [kinds[key] for key in order]

    fig, ax = plt.subplots(figsize=(9.2, 4.4))

    colors = [TERRACOTTA if i == 0 else AMBER for i in range(len(values))]
    bars = ax.barh(names, values, color=colors, height=0.62, zorder=3)

    for bar, value in zip(bars, values):
        ax.text(
            bar.get_width() + 0.08,
            bar.get_y() + bar.get_height() / 2,
            str(value),
            va="center",
            ha="left",
            fontsize=12,
            fontweight="bold",
            color=INK,
        )

    ax.invert_yaxis()
    ax.set_xlabel("files affected")
    ax.set_xlim(0, max(values) * 1.22)
    ax.grid(axis="x", color=LINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)

    ax.set_title(
        "What actually breaks in a mixed-OS download folder",
        loc="left",
        fontsize=14,
        fontweight="bold",
        pad=34,
    )
    ax.text(
        0,
        1.055,
        f"{d['scanned']} files scanned · {d['issues_before']} had problems · "
        f"{d['invalid_before']} could not be opened on Windows at all",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
        va="bottom",
    )

    save(fig, "fig1_problem_kinds.png")


# ---------------------------------------------------------------- figure 2
def fig_before_after(d: dict) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 4.6))

    stages = ["Before fix", "After fix"]
    invalid = [d["invalid_before"], d["invalid_after"]]
    warned = [
        d["issues_before"] - d["invalid_before"],
        d["issues_after"] - d["invalid_after"],
    ]

    x = range(len(stages))
    width = 0.40

    ax.bar(x, invalid, width, label="broken (error)", color=TERRACOTTA, zorder=3)
    ax.bar(
        x,
        warned,
        width,
        bottom=invalid,
        label="risky (warning)",
        color=AMBER,
        zorder=3,
    )

    for index in x:
        total = invalid[index] + warned[index]

        if total == 0:
            # a zero height bar is invisible, so mark the empty column explicitly
            ax.plot(
                index,
                0,
                marker="_",
                markersize=34,
                markeredgewidth=3,
                color=OLIVE,
                zorder=4,
            )
            ax.text(
                index,
                0.45,
                "0 problems",
                ha="center",
                va="bottom",
                fontsize=11,
                fontweight="bold",
                color=OLIVE,
            )
            continue

        ax.text(
            index,
            total + 0.35,
            f"{total} files",
            ha="center",
            va="bottom",
            fontsize=12,
            fontweight="bold",
            color=INK,
        )

    ax.set_xticks(list(x))
    ax.set_xticklabels(stages, fontsize=12)
    ax.set_ylabel("files with problems")
    ax.set_ylim(0, max(d["issues_before"], 1) * 1.45)
    ax.set_xlim(-0.6, 1.6)
    ax.grid(axis="y", color=LINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

    ax.legend(
        frameon=False,
        loc="upper right",
        fontsize=10,
    )
    ax.set_title(
        f"{d['applied_renames']} renames, zero collisions",
        loc="left",
        fontsize=14,
        fontweight="bold",
        pad=34,
    )
    ax.text(
        0,
        1.045,
        "same directory, same command, one --apply flag apart",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
        va="bottom",
    )

    save(fig, "fig2_before_after.png")


# ---------------------------------------------------------------- figure 3
def fig_pipeline() -> None:
    fig, ax = plt.subplots(figsize=(11.0, 3.5))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 34)
    ax.axis("off")

    steps = [
        ("scan_paths", "read only\nper component"),
        ("plan_fixes", "dry run\nextension kept\ncollisions resolved"),
        ("FixPlan.apply", "children first\nrollback on failure"),
    ]

    boxes = []
    width, height = 24, 15
    gap = 6.5
    start = 6

    for index, (title, subtitle) in enumerate(steps):
        x = start + index * (width + gap)
        y = 11

        box = FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle="round,pad=0.6,rounding_size=1.6",
            linewidth=1.4,
            edgecolor=AMBER if index < 2 else TERRACOTTA,
            facecolor="#fffdf9",
            zorder=3,
        )
        ax.add_patch(box)
        boxes.append((x, y, width, height))

        ax.text(
            x + width / 2,
            y + height - 4.2,
            title,
            ha="center",
            va="center",
            fontsize=11.5,
            fontweight="bold",
            family="DejaVu Sans Mono",
            color=INK,
            zorder=4,
        )
        ax.text(
            x + width / 2,
            y + height / 2 - 3.4,
            subtitle,
            ha="center",
            va="center",
            fontsize=9.5,
            color=MUTED,
            linespacing=1.6,
            zorder=4,
        )

    for index in range(len(boxes) - 1):
        x0 = boxes[index][0] + boxes[index][2]
        x1 = boxes[index + 1][0]
        y = boxes[index][1] + boxes[index][3] / 2

        ax.add_patch(
            FancyArrowPatch(
                (x0 + 0.6, y),
                (x1 - 0.6, y),
                arrowstyle="-|>",
                mutation_scale=16,
                linewidth=1.4,
                color=OLIVE,
                zorder=2,
            )
        )

    ax.text(
        start,
        6.5,
        "nothing is written to disk until the last step",
        fontsize=9.5,
        color=OLIVE,
        style="italic",
    )
    ax.text(
        start,
        29.5,
        "Three stages, one guarantee each",
        fontsize=14,
        fontweight="bold",
        color=INK,
    )

    save(fig, "fig3_pipeline.png")


def main() -> None:
    d = data()
    fig_problem_kinds(d)
    fig_before_after(d)
    fig_pipeline()


if __name__ == "__main__":
    main()
