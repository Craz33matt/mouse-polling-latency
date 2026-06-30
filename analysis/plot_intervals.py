#!/usr/bin/env python3
"""
Mouse polling latency analysis.

Loads CLOCK_MONOTONIC-stamped evdev timestamps, computes inter-report intervals,
filters dropped/coalesced-report outliers, and produces four publication-quality
figures in figures/.

Run from repo root:
    python analysis/plot_intervals.py
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "raw"
FIG_DIR = REPO_ROOT / "figures"
FIG_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Dataset definitions
# rate_hz is the configured polling rate; actual observed rate may differ.
# ---------------------------------------------------------------------------
DATASETS = [
    dict(key="1khz_preempt",  file="1khz_preempt.csv",  rate_hz=1000, kernel="preempt", label="1kHz Preempt"),
    dict(key="1khz_stock",    file="1khz_stock.csv",    rate_hz=1000, kernel="stock",   label="1kHz Stock"),
    dict(key="2khz_preempt",  file="2khz_preempt.csv",  rate_hz=2000, kernel="preempt", label="2kHz Preempt"),
    dict(key="2khz_stock",    file="2khz_stock.csv",    rate_hz=2000, kernel="stock",   label="2kHz Stock"),
    dict(key="4khz_preempt",  file="4khz_preempt.csv",  rate_hz=4000, kernel="preempt", label="4kHz Preempt"),
    dict(key="4khz_stock",    file="4khz_stock.csv",    rate_hz=4000, kernel="stock",   label="4kHz Stock"),
    # 8kHz: mouse configured at 8kHz but usbipd/vhci_hcd caps throughput at ~3,940 Hz.
    # The observed interval is therefore ~250 µs, not 125 µs — use that as the outlier
    # reference so double-report gaps (~500 µs) aren't falsely flagged.
    # Included in stats table and timeseries only; excluded from distribution/tail plots.
    dict(key="8khz_preempt",  file="8khz_preempt.csv",  rate_hz=8000, kernel="preempt", label="8kHz Preempt",
         expected_us=250.0,
         note="observed ~3,940 Hz (usbipd/vhci_hcd throughput cap; 250 µs reference used)"),
]

# Nominal expected intervals by configured rate (µs).
# Datasets may override via expected_us when the observed rate differs from the nominal rate.
EXPECTED_US: dict[int, float] = {1000: 1000.0, 2000: 500.0, 4000: 250.0, 8000: 125.0}
OUTLIER_FACTOR = 3.0

# Rates included in distribution/tail-percentile plots (preempt + stock pairs at each rate).
DIST_RATES = [1000, 2000, 4000]

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
KERNEL_COLOR = {"preempt": "#29B6F6", "stock": "#FFA726"}

# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------
TITLE_FS  = 16
LABEL_FS  = 13
TICK_FS   = 11
LEGEND_FS = 11
FIG_SIZE  = (19.2, 10.8)
DPI       = 150


def apply_dark_style() -> None:
    plt.style.use("dark_background")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_intervals(csv_path: Path, expected_us: float) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (clean_intervals_µs, outlier_intervals_µs, total_interval_count)."""
    df = pd.read_csv(csv_path)
    df = df.sort_values("timestamp_s").reset_index(drop=True)
    intervals = df["timestamp_s"].diff().dropna() * 1_000_000  # s → µs
    threshold = expected_us * OUTLIER_FACTOR
    mask_ok = intervals <= threshold
    return intervals[mask_ok].to_numpy(), intervals[~mask_ok].to_numpy(), len(intervals)


def compute_stats(clean: np.ndarray, outliers: np.ndarray, n_intervals: int, label: str) -> dict:
    return dict(
        label=label,
        n_reports=n_intervals + 1,
        n_outliers=len(outliers),
        mean=float(np.mean(clean)),
        median=float(np.median(clean)),
        std=float(np.std(clean)),
        p95=float(np.percentile(clean, 95)),
        p99=float(np.percentile(clean, 99)),
        p999=float(np.percentile(clean, 99.9)),
        imax=float(np.max(clean)),
    )


# ---------------------------------------------------------------------------
# Build in-memory dataset
# ---------------------------------------------------------------------------
data: dict[str, dict] = {}
stats_rows: list[dict] = []

for ds in DATASETS:
    path = DATA_DIR / ds["file"]
    if not path.exists():
        print(f"WARNING: {path} not found — skipping.", file=sys.stderr)
        continue
    # Use per-dataset override when the observed rate differs from the nominal rate_hz.
    expected = ds.get("expected_us", EXPECTED_US[ds["rate_hz"]])
    clean, outliers, n_iv = load_intervals(path, expected)
    data[ds["key"]] = dict(
        clean=clean, outliers=outliers, n_intervals=n_iv,
        rate_hz=ds["rate_hz"], kernel=ds["kernel"], label=ds["label"],
        expected_us=expected,
        note=ds.get("note", ""),
    )
    stats_rows.append(compute_stats(clean, outliers, n_iv, ds["label"]))

stats_df = pd.DataFrame(stats_rows)


# ---------------------------------------------------------------------------
# Figure 1 — interval_distributions.png
# KDE + histogram, preempt vs stock, for DIST_RATES side by side.
# X-axis zoomed to ±30% of the expected interval so tail detail is visible.
# ---------------------------------------------------------------------------
def plot_distributions() -> None:
    apply_dark_style()
    rate_titles = {
        1000: "1 kHz  (expected 1000 µs)",
        2000: "2 kHz  (expected 500 µs)",
        4000: "4 kHz  (expected 250 µs)",
    }
    fig, axes = plt.subplots(1, len(DIST_RATES), figsize=FIG_SIZE, dpi=DPI)
    fig.suptitle(
        "Inter-Report Interval Distributions: Preempt vs Stock Kernel",
        fontsize=TITLE_FS, fontweight="bold", y=0.995,
    )

    for ax, rate in zip(axes, DIST_RATES):
        # Use the preempt entry's expected_us as the panel reference (both kernels share it).
        ref_key  = f"{rate // 1000}khz_preempt"
        expected = data[ref_key]["expected_us"] if ref_key in data else EXPECTED_US[rate]
        zoom_lo  = expected * 0.70
        zoom_hi  = expected * 1.30

        for kernel in ("preempt", "stock"):
            key = f"{rate // 1000}khz_{kernel}"
            if key not in data:
                continue
            vals  = data[key]["clean"]
            color = KERNEL_COLOR[kernel]
            label = data[key]["label"]

            # Histogram over zoom window (density)
            vals_zoom = vals[(vals >= zoom_lo) & (vals <= zoom_hi)]
            ax.hist(vals_zoom, bins=120, density=True, alpha=0.25,
                    color=color, linewidth=0)

            # KDE fitted on full clean distribution, evaluated over zoom window
            if len(vals_zoom) > 10:
                kde  = gaussian_kde(vals, bw_method="silverman")
                xk   = np.linspace(zoom_lo, zoom_hi, 800)
                ax.plot(xk, kde(xk), color=color, linewidth=2.2, label=label)

        ax.axvline(expected, color="#777777", linewidth=1.2, linestyle="--",
                   label=f"Ideal {int(expected)} µs")
        ax.set_xlim(zoom_lo, zoom_hi)
        ax.set_xlabel("Interval (µs)", fontsize=LABEL_FS)
        ax.set_ylabel("Density", fontsize=LABEL_FS)
        ax.set_title(rate_titles[rate], fontsize=LABEL_FS + 1, fontweight="bold")
        ax.tick_params(labelsize=TICK_FS)
        ax.xaxis.set_major_formatter(ticker.FormatStrFormatter("%.0f"))
        ax.legend(fontsize=LEGEND_FS)
        ax.grid(alpha=0.15)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = FIG_DIR / "interval_distributions.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# Figure 2 — tail_percentiles.png
# Grouped bar chart: p95 / p99 / p99.9 for each condition in DIST_RATES.
# ---------------------------------------------------------------------------
def plot_tail_percentiles() -> None:
    apply_dark_style()

    conditions = []
    for rate in DIST_RATES:
        for kernel in ("preempt", "stock"):
            key = f"{rate // 1000}khz_{kernel}"
            if key in data:
                conditions.append(key)

    pct_keys    = ["p95", "p99", "p999"]
    pct_labels  = ["p95", "p99", "p99.9"]
    pct_colors  = ["#26C6DA", "#0097A7", "#006064"]

    n_cond    = len(conditions)
    n_pct     = len(pct_keys)
    bar_width = 0.70 / n_pct
    x         = np.arange(n_cond)

    fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=DPI)
    fig.suptitle(
        "Tail Latency Percentiles (p95 / p99 / p99.9) by Condition",
        fontsize=TITLE_FS, fontweight="bold",
    )

    for pi, (pk, pl, pc) in enumerate(zip(pct_keys, pct_labels, pct_colors)):
        vals = []
        for key in conditions:
            row = stats_df[stats_df["label"] == data[key]["label"]]
            vals.append(float(row[pk].iloc[0]) if not row.empty else 0.0)

        offset = (pi - n_pct / 2 + 0.5) * bar_width
        bars   = ax.bar(x + offset, vals, width=bar_width * 0.88,
                        color=pc, label=pl, zorder=3)

        for bar, v in zip(bars, vals):
            if v > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.4,
                    f"{v:.1f}",
                    ha="center", va="bottom",
                    fontsize=8, color="white", rotation=90,
                )

    # Reference lines at expected interval per rate group.
    # Group by (rate_hz, expected_us) so an override like 8kHz→250µs doesn't collide.
    group_spans: dict[tuple[int, float], list[int]] = {}
    for i, key in enumerate(conditions):
        gk = (data[key]["rate_hz"], data[key]["expected_us"])
        group_spans.setdefault(gk, []).append(i)

    drawn_labels: set[str] = set()
    for (rate, exp), idxs in group_spans.items():
        lo    = x[min(idxs)] - 0.45
        hi    = x[max(idxs)] + 0.45
        lbl   = f"Ideal {int(exp)} µs"
        label = lbl if lbl not in drawn_labels else "_nolegend_"
        drawn_labels.add(lbl)
        ax.hlines(exp, lo, hi, colors="#666666", linestyles="--",
                  linewidth=1.2, label=label, zorder=2)

    x_labels = []
    for key in conditions:
        rate = data[key]["rate_hz"]
        kernel = data[key]["kernel"].capitalize()
        x_labels.append(f"{rate // 1000} kHz\n{kernel}")

    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, fontsize=TICK_FS)
    ax.set_xlabel("Condition", fontsize=LABEL_FS)
    ax.set_ylabel("Interval (µs)", fontsize=LABEL_FS)
    ax.tick_params(axis="y", labelsize=TICK_FS)
    ax.legend(fontsize=LEGEND_FS)
    ax.grid(axis="y", alpha=0.20, zorder=0)

    fig.tight_layout()
    out = FIG_DIR / "tail_percentiles.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# Figure 3 — interval_timeseries.png
# 2kHz preempt vs stock: interval (µs) vs report number, first 2000 reports.
# Horizontal reference line at ideal 500 µs.
# ---------------------------------------------------------------------------
N_TIMESERIES = 2000


def load_raw_intervals(key: str) -> np.ndarray:
    """Load all intervals (including outliers) for timeseries display."""
    path = DATA_DIR / data[key]["file"] if "file" in data[key] else None
    # Reconstruct filename from key
    fname = f"{key}.csv"
    ts = pd.read_csv(DATA_DIR / fname).sort_values("timestamp_s")["timestamp_s"].to_numpy()
    return np.diff(ts) * 1_000_000


# Store filenames in data dict for convenience
for ds in DATASETS:
    if ds["key"] in data:
        data[ds["key"]]["file"] = ds["file"]


def plot_timeseries() -> None:
    apply_dark_style()
    fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=DPI)
    fig.suptitle(
        "Interval Time-Series: 2 kHz Preempt vs Stock  (First 2000 Reports)",
        fontsize=TITLE_FS, fontweight="bold",
    )

    for key, color in [("2khz_preempt", KERNEL_COLOR["preempt"]),
                       ("2khz_stock",   KERNEL_COLOR["stock"])]:
        if key not in data:
            continue
        iv = load_raw_intervals(key)
        iv_plot = iv[:N_TIMESERIES]
        ax.plot(np.arange(1, len(iv_plot) + 1), iv_plot,
                color=color, linewidth=0.75, alpha=0.88,
                label=data[key]["label"])

    ax.axhline(500.0, color="#777777", linewidth=1.5, linestyle="--",
               label="Ideal 500 µs")
    ax.set_xlabel("Report Number", fontsize=LABEL_FS)
    ax.set_ylabel("Interval (µs)", fontsize=LABEL_FS)
    ax.tick_params(labelsize=TICK_FS)
    ax.legend(fontsize=LEGEND_FS)
    ax.grid(alpha=0.18)

    fig.tight_layout()
    out = FIG_DIR / "interval_timeseries.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# Figure 4 — stats_table.png
# Full stats table rendered as a matplotlib figure.
# ---------------------------------------------------------------------------
def plot_stats_table() -> None:
    apply_dark_style()

    col_headers = [
        "Condition", "Reports", "Outliers",
        "Mean (µs)", "Median (µs)", "Std (µs)",
        "p95 (µs)", "p99 (µs)", "p99.9 (µs)", "Max (µs)",
    ]

    note_keys = {ds["key"] for ds in DATASETS if ds.get("note")}

    table_rows: list[list[str]] = []
    for row in stats_df.itertuples(index=False):
        # Find matching key
        key  = next((ds["key"] for ds in DATASETS if ds["label"] == row.label), None)
        flag = " *" if key in note_keys else ""
        table_rows.append([
            row.label + flag,
            f"{row.n_reports:,}",
            f"{row.n_outliers:,}",
            f"{row.mean:.2f}",
            f"{row.median:.2f}",
            f"{row.std:.3f}",
            f"{row.p95:.2f}",
            f"{row.p99:.2f}",
            f"{row.p999:.2f}",
            f"{row.imax:.2f}",
        ])

    fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=DPI)
    fig.suptitle(
        "Mouse Polling Latency — Full Statistics Summary",
        fontsize=TITLE_FS, fontweight="bold", y=0.97,
    )
    ax.axis("off")

    tbl = ax.table(
        cellText=table_rows,
        colLabels=col_headers,
        loc="center",
        cellLoc="center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(11)
    tbl.scale(1, 2.4)

    # Header row
    for j in range(len(col_headers)):
        cell = tbl[0, j]
        cell.set_facecolor("#1565C0")
        cell.set_text_props(color="white", fontweight="bold")

    # Data rows — alternating shades, highlight 8kHz specially
    for i, row in enumerate(table_rows, start=1):
        is_8k   = "8kHz" in row[0]
        base_fc = "#4A1942" if is_8k else ("#1A237E" if i % 2 == 0 else "#0D1B4B")
        for j in range(len(col_headers)):
            cell = tbl[i, j]
            cell.set_facecolor(base_fc)
            cell.set_text_props(color="white")

    ax.text(
        0.5, 0.03,
        "* 8kHz Preempt: observed rate ~3,800 Hz due to usbipd/vhci_hcd throughput cap — "
        "does not represent true 8 kHz behaviour",
        ha="center", va="bottom", transform=ax.transAxes,
        fontsize=10, color="#FFCC02", style="italic",
    )

    fig.tight_layout(rect=[0, 0.04, 1, 0.96])
    out = FIG_DIR / "stats_table.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# Terminal summary table
# ---------------------------------------------------------------------------
def print_summary() -> None:
    sep = "=" * 102
    hdr = (
        f"{'Condition':<20} {'Reports':>8} {'Outliers':>9} "
        f"{'Mean µs':>9} {'Median':>9} {'Std':>8} "
        f"{'p95':>8} {'p99':>8} {'p99.9':>9} {'Max':>10}"
    )
    print(f"\n{sep}")
    print(hdr)
    print(sep)
    for row in stats_df.itertuples(index=False):
        key  = next((ds["key"] for ds in DATASETS if ds["label"] == row.label), "")
        flag = " *" if key in {ds["key"] for ds in DATASETS if ds.get("note")} else ""
        print(
            f"{row.label + flag:<20} {row.n_reports:>8,} {row.n_outliers:>9,} "
            f"{row.mean:>9.2f} {row.median:>9.2f} {row.std:>8.3f} "
            f"{row.p95:>8.2f} {row.p99:>8.2f} {row.p999:>9.2f} {row.imax:>10.2f}"
        )
    print(sep)
    print("* 8kHz Preempt: observed ~3,800 Hz (usbipd/vhci_hcd throughput cap)")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not data:
        print("No data files found — check DATA_DIR path.", file=sys.stderr)
        sys.exit(1)

    print("Generating figures …")
    plot_distributions()
    plot_tail_percentiles()
    plot_timeseries()
    plot_stats_table()
    print_summary()
    print("Done.")
