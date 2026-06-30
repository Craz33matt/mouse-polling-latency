#!/usr/bin/env python3
"""
plot_intervals.py

Reads all per-condition captures from data/raw/, aggregates across n=5 runs,
and produces publication-quality figures for the README.

Figures produced:
  figures/interval_distributions.png  — KDE + histogram per rate, preempt vs stock pooled
  figures/tail_percentiles.png        — p95/p99/p99.9 grouped bar chart (pooled)
  figures/per_run_consistency.png     — boxplots showing within-condition variance across runs
  figures/interval_timeseries.png     — 2kHz 2000-report window, preempt vs stock (run 1)
  figures/stats_table.png             — full stats table rendered as figure

Stats also printed to stdout.

Usage (from repo root, venv active):
    python analysis/plot_intervals.py
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR  = REPO_ROOT / "data" / "raw"
FIG_DIR   = REPO_ROOT / "figures"
FIG_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DIST_RATES     = [1000, 2000, 4000]   # Hz — rates included in distribution/tail/consistency plots
OUTLIER_FACTOR = 3.0                  # intervals > factor × expected are dropped as SYN_DROPPED gaps
N_TIMESERIES   = 2000                 # number of consecutive reports to show in timeseries figure

# Nominal expected intervals (µs) by configured polling rate.
EXPECTED_US: dict[int, float] = {1000: 1000.0, 2000: 500.0, 4000: 250.0, 8000: 125.0}

KERNEL_COLOR = {"preempt": "#29B6F6", "stock": "#FFA726"}

TITLE_FS  = 16
LABEL_FS  = 13
TICK_FS   = 11
LEGEND_FS = 11
FIG_SIZE  = (19.2, 10.8)
DPI       = 150


def apply_dark_style() -> None:
    plt.style.use("dark_background")


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def discover_runs() -> dict[tuple[int, str], list[Path]]:
    """
    Return {(rate_hz, kernel): [sorted list of CSV paths]} for all conditions.
    Naming convention: {N}khz_{kernel}.csv (run 1), {N}khz_{kernel}2.csv (run 2), …
    """
    pattern = re.compile(r"^(\d+)khz_(preempt|stock)(\d*)$")
    runs: dict[tuple[int, str], list[Path]] = defaultdict(list)
    for p in sorted(DATA_DIR.glob("*.csv")):
        m = pattern.match(p.stem)
        if not m:
            continue
        rate_hz = int(m.group(1)) * 1000
        kernel  = m.group(2)
        runs[(rate_hz, kernel)].append(p)
    return dict(runs)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_intervals(csv_path: Path, expected_us: float) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (clean_µs, outlier_µs, total_interval_count)."""
    df = pd.read_csv(csv_path).sort_values("timestamp_s").reset_index(drop=True)
    intervals = df["timestamp_s"].diff().dropna() * 1_000_000   # s → µs
    threshold = expected_us * OUTLIER_FACTOR
    mask_ok   = intervals <= threshold
    return intervals[mask_ok].to_numpy(), intervals[~mask_ok].to_numpy(), len(intervals)


def compute_stats(clean: np.ndarray, outliers: np.ndarray,
                  n_intervals: int, label: str, n_runs: int) -> dict:
    return dict(
        label=label,
        n_runs=n_runs,
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
run_map = discover_runs()

# per_run[rate_hz][kernel] = list of clean interval arrays (one per run)
per_run: dict[int, dict[str, list[np.ndarray]]] = defaultdict(lambda: defaultdict(list))

# pooled[rate_hz][kernel] = clean intervals concatenated across all runs
pooled: dict[int, dict[str, np.ndarray]] = defaultdict(dict)

stats_rows: list[dict] = []

for (rate_hz, kernel), paths in sorted(run_map.items()):
    # 8kHz usbipd/vhci_hcd throughput cap means observed rate is ~3,940 Hz;
    # use 250µs as reference so double-report gaps aren't falsely flagged.
    expected = 250.0 if rate_hz == 8000 else EXPECTED_US.get(rate_hz, 1000.0)

    all_clean:    list[np.ndarray] = []
    all_outliers: list[np.ndarray] = []
    total_iv = 0

    for p in paths:
        clean, outliers, n_iv = load_intervals(p, expected)
        per_run[rate_hz][kernel].append(clean)
        all_clean.append(clean)
        all_outliers.append(outliers)
        total_iv += n_iv

    pooled_clean    = np.concatenate(all_clean)    if all_clean    else np.array([])
    pooled_outliers = np.concatenate(all_outliers) if all_outliers else np.array([])
    pooled[rate_hz][kernel] = pooled_clean

    label = f"{rate_hz // 1000} kHz {'Preempt' if kernel == 'preempt' else 'Stock'}"
    stats_rows.append(compute_stats(pooled_clean, pooled_outliers, total_iv, label, len(paths)))

stats_df = pd.DataFrame(stats_rows)

print("Discovered conditions:")
for (rate_hz, kernel), paths in sorted(run_map.items()):
    print(f"  {rate_hz // 1000} kHz {kernel}: {len(paths)} run(s)")


# ---------------------------------------------------------------------------
# Figure 1 — interval_distributions.png
# Pooled KDE + histogram per rate, preempt vs stock overlaid.
# X-axis zoomed to ±30% of expected interval so distribution detail is visible.
# ---------------------------------------------------------------------------
def plot_distributions() -> None:
    apply_dark_style()
    fig, axes = plt.subplots(1, len(DIST_RATES), figsize=FIG_SIZE, dpi=DPI)
    fig.suptitle(
        "Inter-Report Interval Distributions: Preempt vs Stock  (n=5 runs pooled)",
        fontsize=TITLE_FS, fontweight="bold", y=0.995,
    )

    for ax, rate in zip(axes, DIST_RATES):
        expected = EXPECTED_US[rate]
        zoom_lo  = expected * 0.70
        zoom_hi  = expected * 1.30

        for kernel in ("preempt", "stock"):
            if kernel not in pooled.get(rate, {}):
                continue
            vals   = pooled[rate][kernel]
            color  = KERNEL_COLOR[kernel]
            n_runs = len(per_run[rate][kernel])
            label  = f"{'Preempt' if kernel == 'preempt' else 'Stock'}  (n={n_runs})"

            vals_zoom = vals[(vals >= zoom_lo) & (vals <= zoom_hi)]
            ax.hist(vals_zoom, bins=120, density=True, alpha=0.25, color=color, linewidth=0)

            if len(vals_zoom) > 10:
                kde = gaussian_kde(vals, bw_method="silverman")
                xk  = np.linspace(zoom_lo, zoom_hi, 800)
                ax.plot(xk, kde(xk), color=color, linewidth=2.2, label=label)

            p99 = np.percentile(vals, 99)
            ax.axvline(p99, color=color, linestyle="--", linewidth=1.0, alpha=0.7)

        ax.axvline(expected, color="#777777", linewidth=1.2, linestyle=":",
                   label=f"Ideal {int(expected)} µs")
        ax.set_xlim(zoom_lo, zoom_hi)
        ax.set_xlabel("Interval (µs)", fontsize=LABEL_FS)
        ax.set_ylabel("Density", fontsize=LABEL_FS)
        ax.set_title(f"{rate // 1000} kHz  (expected {int(expected)} µs)",
                     fontsize=LABEL_FS + 1, fontweight="bold")
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
# Grouped bar chart: p95 / p99 / p99.9 for each condition (pooled across runs).
# Heights are raw µs values; dashed reference lines show the ideal interval.
# ---------------------------------------------------------------------------
def plot_tail_percentiles() -> None:
    apply_dark_style()

    conditions = [(r, k) for r in DIST_RATES for k in ("preempt", "stock")
                  if k in pooled.get(r, {})]

    pct_keys   = ["p95", "p99", "p999"]
    pct_labels = ["p95", "p99", "p99.9"]
    pct_colors = ["#26C6DA", "#0097A7", "#006064"]

    n_cond    = len(conditions)
    n_pct     = len(pct_keys)
    bar_width = 0.70 / n_pct
    x         = np.arange(n_cond)

    fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=DPI)
    fig.suptitle(
        "Tail Latency Percentiles (p95 / p99 / p99.9) by Condition  (n=5 runs pooled)",
        fontsize=TITLE_FS, fontweight="bold",
    )

    for pi, (pk, pl, pc) in enumerate(zip(pct_keys, pct_labels, pct_colors)):
        vals = []
        for rate, kernel in conditions:
            label = f"{rate // 1000} kHz {'Preempt' if kernel == 'preempt' else 'Stock'}"
            row   = stats_df[stats_df["label"] == label]
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

    drawn: set[str] = set()
    for rate, _ in conditions:
        exp = EXPECTED_US[rate]
        lbl = f"Ideal {int(exp)} µs"
        idxs = [j for j, (r, _) in enumerate(conditions) if r == rate]
        lo, hi = x[min(idxs)] - 0.45, x[max(idxs)] + 0.45
        ax.hlines(exp, lo, hi, colors="#666666", linestyles="--",
                  linewidth=1.2, label=lbl if lbl not in drawn else "_nolegend_", zorder=2)
        drawn.add(lbl)

    x_labels = [f"{r // 1000} kHz\n{'Preempt' if k == 'preempt' else 'Stock'}"
                for r, k in conditions]
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
# Figure 3 — per_run_consistency.png  (new with n=5)
# Boxplots of each individual run per condition.
# Tight clustering across all 5 runs validates that results are reproducible,
# not artifacts of a single lucky or unlucky capture.
# ---------------------------------------------------------------------------
def plot_per_run_consistency() -> None:
    apply_dark_style()

    n_rates = len(DIST_RATES)
    fig, axes = plt.subplots(1, n_rates, figsize=FIG_SIZE, dpi=DPI)
    fig.suptitle(
        "Within-Condition Variance Across Runs (n=5)  — IQR Boxplots, Outliers Hidden",
        fontsize=TITLE_FS, fontweight="bold", y=0.995,
    )

    for ax, rate in zip(axes, DIST_RATES):
        plot_data:   list[np.ndarray] = []
        plot_labels: list[str]        = []
        plot_colors: list[str]        = []

        for kernel in ("preempt", "stock"):
            for i, run_ivs in enumerate(per_run[rate].get(kernel, []), start=1):
                plot_data.append(run_ivs)
                plot_labels.append(f"{'Pre' if kernel == 'preempt' else 'Stk'} r{i}")
                plot_colors.append(KERNEL_COLOR[kernel])

        if not plot_data:
            continue

        bp = ax.boxplot(
            plot_data, tick_labels=plot_labels,
            patch_artist=True, showfliers=False,
            medianprops=dict(color="white", linewidth=2),
            whiskerprops=dict(linewidth=1.2),
            capprops=dict(linewidth=1.2),
        )
        for patch, color in zip(bp["boxes"], plot_colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)

        ax.axhline(EXPECTED_US[rate], color="#777777", linewidth=1.2, linestyle="--",
                   label=f"Ideal {int(EXPECTED_US[rate])} µs", zorder=2)

        ax.set_title(f"{rate // 1000} kHz", fontsize=LABEL_FS + 1, fontweight="bold")
        ax.set_ylabel("Interval (µs)", fontsize=LABEL_FS)
        ax.tick_params(labelsize=TICK_FS - 1)
        patches = [mpatches.Patch(color=KERNEL_COLOR[k], alpha=0.6,
                                  label="Preempt" if k == "preempt" else "Stock")
                   for k in ("preempt", "stock")]
        ax.legend(handles=patches, fontsize=LEGEND_FS)
        ax.grid(axis="y", alpha=0.15)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = FIG_DIR / "per_run_consistency.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# Figure 4 — interval_timeseries.png
# 2kHz preempt vs stock: 2000-report window centred at the midpoint of run 1.
# Shows the raw shape of scheduling variation, not just summary statistics.
# ---------------------------------------------------------------------------
def plot_timeseries() -> None:
    apply_dark_style()
    fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=DPI)

    title_range: tuple[int, int] | None = None

    for kernel, color in [("preempt", KERNEL_COLOR["preempt"]),
                           ("stock",   KERNEL_COLOR["stock"])]:
        paths = run_map.get((2000, kernel), [])
        if not paths:
            continue
        ts      = pd.read_csv(paths[0]).sort_values("timestamp_s")["timestamp_s"].to_numpy()
        iv      = np.diff(ts) * 1_000_000   # µs
        mid     = len(iv) // 2
        start   = mid - N_TIMESERIES // 2
        end     = start + N_TIMESERIES
        iv_plot = iv[start:end]
        report_nums = np.arange(start + 1, end + 1)

        if title_range is None:
            title_range = (int(report_nums[0]), int(report_nums[-1]))

        label = f"2 kHz {'Preempt' if kernel == 'preempt' else 'Stock'}"
        ax.plot(report_nums, iv_plot, color=color, linewidth=0.75, alpha=0.88, label=label)

    r0, r1 = title_range or (0, N_TIMESERIES)
    fig.suptitle(
        f"Interval Time-Series: 2 kHz Preempt vs Stock  (Run 1, Reports {r0:,}–{r1:,})",
        fontsize=TITLE_FS, fontweight="bold",
    )

    ax.axhline(500.0, color="#777777", linewidth=1.5, linestyle="--", label="Ideal 500 µs")
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
# Figure 5 — stats_table.png
# Full pooled stats rendered as a matplotlib figure.
# ---------------------------------------------------------------------------
def plot_stats_table() -> None:
    apply_dark_style()

    col_headers = [
        "Condition", "Runs", "Reports", "Outliers",
        "Mean (µs)", "Median (µs)", "Std (µs)",
        "p95 (µs)", "p99 (µs)", "p99.9 (µs)", "Max (µs)",
    ]

    table_rows: list[list[str]] = []
    for row in stats_df.itertuples(index=False):
        table_rows.append([
            row.label,
            str(row.n_runs),
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
        "Mouse Polling Latency — Full Statistics Summary  (n=5 runs pooled per condition)",
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
    tbl.set_fontsize(10)
    tbl.scale(1, 2.2)

    for j in range(len(col_headers)):
        cell = tbl[0, j]
        cell.set_facecolor("#1565C0")
        cell.set_text_props(color="white", fontweight="bold")

    for i in range(len(table_rows)):
        for j in range(len(col_headers)):
            cell = tbl[i + 1, j]
            cell.set_facecolor("#1A237E" if i % 2 == 0 else "#0D1B4B")
            cell.set_text_props(color="white")

    fig.tight_layout(rect=[0, 0.02, 1, 0.95])
    out = FIG_DIR / "stats_table.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# Terminal summary
# ---------------------------------------------------------------------------
def print_summary() -> None:
    sep = "=" * 114
    hdr = (f"{'Condition':<22} {'Runs':>4} {'Reports':>9} {'Outliers':>9} "
           f"{'Mean µs':>9} {'Median':>9} {'Std':>8} "
           f"{'p95':>8} {'p99':>8} {'p99.9':>9} {'Max':>10}")
    print(f"\n{sep}\n{hdr}\n{sep}")
    for row in stats_df.itertuples(index=False):
        print(f"{row.label:<22} {row.n_runs:>4} {row.n_reports:>9,} {row.n_outliers:>9,} "
              f"{row.mean:>9.2f} {row.median:>9.2f} {row.std:>8.3f} "
              f"{row.p95:>8.2f} {row.p99:>8.2f} {row.p999:>9.2f} {row.imax:>10.2f}")
    print(sep + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not run_map:
        print("No data files found — check DATA_DIR path.", file=sys.stderr)
        sys.exit(1)

    print("Generating figures…")
    plot_distributions()
    plot_tail_percentiles()
    plot_per_run_consistency()
    plot_timeseries()
    plot_stats_table()
    print_summary()
    print("Done. Figures written to figures/")
