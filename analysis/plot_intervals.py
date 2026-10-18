#!/usr/bin/env python3
"""
plot_intervals.py

Reads all per-condition captures from data/raw/, aggregates across n=5 runs,
and produces publication-quality figures for the README.

Figures produced:
  figures/interval_distributions.png  — KDE + histogram per rate, preempt vs stock pooled
  figures/tail_percentiles.png        — p95/p99/p99.9 grouped bar chart (pooled)
  figures/per_run_consistency.png     — boxplots showing within-condition variance across runs
  figures/interval_timeseries.png     — 2kHz full-capture small multiples (5 runs × 2 kernels)
                                         plus rolling std dev (all 5 runs)
  figures/stats_table.png             — full stats table rendered as figure

Stats also printed to stdout.

Usage (from repo root, venv active):
    python analysis/plot_intervals.py
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from scipy.stats import fisher_exact, gaussian_kde

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

# Nominal expected intervals (µs) by configured polling rate.
EXPECTED_US: dict[int, float] = {1000: 1000.0, 2000: 500.0, 4000: 250.0, 8000: 125.0}

KERNEL_COLOR = {"preempt": "#29B6F6", "stock": "#FFA726"}

# stress-ng parameters for the 2kHz stress captures (identical on both kernels).
STRESS_PARAMS: dict[str, str] = {
    "cpu":      "stress-ng --cpu 4",
    "mem":      "stress-ng --vm 2 --vm-bytes 50%",
    "combined": "stress-ng --cpu 4 --vm 1 --vm-bytes 50% --io 1",
}

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
# Top: small multiples of the full capture for all 5 runs × 2 kernels at 2kHz,
#      downsampled 10x, so a reader can confirm the result isn't cherry-picked
#      from one window of one run.
# Bottom: rolling std dev (window=500) for all 5 runs, showing whether jitter
#      is stationary across the capture or clustered in bursts.
# ---------------------------------------------------------------------------
def plot_timeseries() -> None:
    apply_dark_style()

    fig = plt.figure(figsize=(19.2, 22), dpi=DPI)
    outer = gridspec.GridSpec(2, 1, height_ratios=[7, 8], hspace=0.25, figure=fig)

    # --- Top: 5 runs × 2 kernels small multiples ---
    top_gs = gridspec.GridSpecFromSubplotSpec(5, 2, subplot_spec=outer[0],
                                              hspace=0.55, wspace=0.15)

    DOWNSAMPLE = 10
    kernels_order = ["preempt", "stock"]

    # Shared y-limits across all small multiples, robust to extreme outliers.
    all_vals = [run_ivs[::DOWNSAMPLE]
                for kernel in kernels_order
                for run_ivs in per_run[2000].get(kernel, [])]
    if all_vals:
        concat_all = np.concatenate(all_vals)
        y_lo, y_hi = np.percentile(concat_all, [0.5, 99.5])
        pad = (y_hi - y_lo) * 0.1
        y_lo, y_hi = y_lo - pad, y_hi + pad
    else:
        y_lo, y_hi = 0.0, 1000.0

    for col, kernel in enumerate(kernels_order):
        runs = per_run[2000].get(kernel, [])
        for row in range(5):
            ax = fig.add_subplot(top_gs[row, col])
            if row < len(runs):
                iv = runs[row][::DOWNSAMPLE]
                x  = np.arange(1, len(iv) + 1) * DOWNSAMPLE
                ax.plot(x, iv, color=KERNEL_COLOR[kernel], linewidth=0.5, alpha=0.85)
                ax.axhline(500.0, color="#777777", linewidth=1.0, linestyle="--")
                ax.set_ylim(y_lo, y_hi)
                ax.set_title(f"{'Preempt' if kernel == 'preempt' else 'Stock'} run {row + 1}",
                             fontsize=LABEL_FS - 2, fontweight="bold")
            ax.tick_params(labelsize=TICK_FS - 3)
            if row == 4:
                ax.set_xlabel("Report #", fontsize=LABEL_FS - 3)
            if col == 0:
                ax.set_ylabel("µs", fontsize=LABEL_FS - 3)
            ax.grid(alpha=0.15)

    fig.text(0.5, 0.965, "2 kHz — All Runs, Full Capture (every 10th report shown)",
             ha="center", fontsize=TITLE_FS, fontweight="bold")

    # --- Bottom: rolling std dev, one subplot per run, preempt vs stock overlaid ---
    ROLL_WINDOW = 500
    bottom_gs = gridspec.GridSpecFromSubplotSpec(5, 1, subplot_spec=outer[1], hspace=0.55)

    preempt_runs = per_run[2000].get("preempt", [])
    stock_runs   = per_run[2000].get("stock", [])

    # Shared y-limits across all 5 rolling-std subplots for easy comparison.
    roll_all = [pd.Series(iv).rolling(ROLL_WINDOW).std().dropna().to_numpy()
                for iv in preempt_runs + stock_runs]
    if roll_all:
        roll_hi = np.percentile(np.concatenate(roll_all), 99.5) * 1.1
    else:
        roll_hi = 1.0

    for row in range(5):
        ax_roll = fig.add_subplot(bottom_gs[row, 0])
        for kernel, runs, color in [("preempt", preempt_runs, KERNEL_COLOR["preempt"]),
                                    ("stock",   stock_runs,   KERNEL_COLOR["stock"])]:
            if row >= len(runs):
                continue
            iv = runs[row]
            roll_std = pd.Series(iv).rolling(ROLL_WINDOW).std().to_numpy()
            x = np.arange(1, len(iv) + 1)
            label = "Preempt" if kernel == "preempt" else "Stock"
            ax_roll.plot(x, roll_std, color=color, linewidth=0.8, alpha=0.9, label=label)

        ax_roll.axhline(0.0, color="#777777", linewidth=1.0, linestyle="--")
        ax_roll.set_ylim(0, roll_hi)
        ax_roll.set_title(f"Run {row + 1}", fontsize=LABEL_FS, fontweight="bold")
        ax_roll.set_ylabel("Std (µs)", fontsize=LABEL_FS - 2)
        ax_roll.tick_params(labelsize=TICK_FS - 1)
        if row == 4:
            ax_roll.set_xlabel("Report Number", fontsize=LABEL_FS)
        if row == 0:
            ax_roll.legend(fontsize=LEGEND_FS, loc="upper right")
        ax_roll.grid(alpha=0.18)

    bottom_pos = outer[1].get_position(fig)
    fig.text(0.5, bottom_pos.y1 + 0.012,
             f"Rolling Std Dev (window={ROLL_WINDOW} reports) — 2 kHz, Preempt vs Stock per Run",
             ha="center", fontsize=TITLE_FS, fontweight="bold")

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
# Figure 6 — stress_comparison.png
# Std dev and p99 at 2kHz under background stress, preempt vs stock.
# Idle is the 5 per-run values (median bar, min–max error bar, individual dots);
# stress conditions are single captures. Shaded bands show each kernel's idle
# run-to-run range so a stress bar can be judged against normal variation.
# Also writes figures/stress_stats.md.
# ---------------------------------------------------------------------------
def plot_stress_comparison() -> None:
    expected = EXPECTED_US[2000]
    kernels  = ("preempt", "stock")
    required_preempt = {"preempt": "CONFIG_PREEMPT=y", "stock": "CONFIG_PREEMPT_NONE=y"}
    required_active  = {"preempt": "full", "stock": "none"}

    # --- Validate stress captures before using them ---
    problems: list[str] = []
    for kernel in kernels:
        for cond in STRESS_PARAMS:
            csv_path  = DATA_DIR / f"2khz_{kernel}_stress_{cond}.csv"
            meta_path = csv_path.with_suffix(".meta.json")
            if not csv_path.exists() or not meta_path.exists():
                problems.append(f"{csv_path.name}: CSV or .meta.json sidecar missing")
                continue
            meta = json.loads(meta_path.read_text())
            dropped = meta.get("syn_dropped_events")
            if dropped != 0:
                problems.append(f"{meta_path.name}: syn_dropped_events = {dropped} (expected 0)")
            # Newer captures record the active dynamic-preemption mode; older
            # ones only have the compiled config in preempt_status.
            if "preempt_active" in meta:
                field, want = "preempt_active", required_active[kernel]
                ok = meta["preempt_active"] == want
            else:
                field, want = "preempt_status", required_preempt[kernel]
                ok = want in meta.get("preempt_status", "")
            if not ok:
                problems.append(f"{meta_path.name}: {field} = {meta.get(field, '')!r} "
                                f"(expected {want!r} for a {kernel} capture "
                                f"— possibly mislabeled)")
    if problems:
        raise RuntimeError("Stress capture validation failed:\n  " + "\n  ".join(problems))

    def metrics(clean: np.ndarray, outliers: np.ndarray, n_iv: int) -> dict:
        return dict(
            reports=n_iv + 1,
            outliers=len(outliers),
            std=float(np.std(clean)),
            p99=float(np.percentile(clean, 99)),
            p999=float(np.percentile(clean, 99.9)),
            imax=float(np.max(clean)),
        )

    # --- Idle: per-run metrics (per_run holds clean intervals; counts need a reload) ---
    idle_runs: dict[str, list[dict]] = {}
    for kernel in kernels:
        idle_runs[kernel] = []
        for p, clean in zip(run_map.get((2000, kernel), []), per_run[2000][kernel]):
            _, outliers, n_iv = load_intervals(p, expected)
            idle_runs[kernel].append(metrics(clean, outliers, n_iv))

    idle_range = {k: {m: (min(r[m] for r in idle_runs[k]), max(r[m] for r in idle_runs[k]))
                      for m in ("std", "p99")}
                  for k in kernels}

    # --- Stress: single captures ---
    stress: dict[str, dict[str, dict]] = {k: {} for k in kernels}
    for kernel in kernels:
        for cond in STRESS_PARAMS:
            clean, outliers, n_iv = load_intervals(
                DATA_DIR / f"2khz_{kernel}_stress_{cond}.csv", expected)
            stress[kernel][cond] = metrics(clean, outliers, n_iv)

    # --- Figure ---
    apply_dark_style()
    group_labels = ["Idle (n=5 runs)", "CPU (n=1)", "Memory (n=1)", "Combined (n=1)"]
    conds        = list(STRESS_PARAMS)   # cpu, mem, combined
    bar_width    = 0.35
    x            = np.arange(len(group_labels))
    label_bbox   = dict(boxstyle="round,pad=0.15", fc="black", alpha=0.6, ec="none")

    fig, (ax_std, ax_p99) = plt.subplots(2, 1, figsize=FIG_SIZE, dpi=DPI)

    def draw_panel(ax, metric: str) -> None:
        y_top = 0.0
        for ki, kernel in enumerate(kernels):
            color  = KERNEL_COLOR[kernel]
            name   = "Preempt" if kernel == "preempt" else "Stock"
            offset = (ki - 0.5) * bar_width
            lo, hi = idle_range[kernel][metric]

            ax.axhspan(lo, hi, color=color, alpha=0.08, zorder=1,
                       label=f"{name} idle range")

            idle_vals = [r[metric] for r in idle_runs[kernel]]
            idle_med  = float(np.median(idle_vals))
            heights   = [idle_med] + [stress[kernel][c][metric] for c in conds]
            bars = ax.bar(x + offset, heights, width=bar_width, color=color,
                          label=name, zorder=3)

            # Idle bar: min–max error bar plus the 5 individual run values.
            xc = x[0] + offset
            ax.errorbar(xc, idle_med, yerr=[[idle_med - lo], [hi - idle_med]],
                        fmt="none", ecolor="white", elinewidth=1.4, capsize=6, zorder=4)
            jitter = np.linspace(-0.07, 0.07, len(idle_vals))
            ax.scatter(xc + jitter, idle_vals, s=18, color="white",
                       edgecolors="black", linewidths=0.6, zorder=5)

            for i, (bar, v) in enumerate(zip(bars, heights)):
                y_lbl = hi if i == 0 else v   # idle label clears the error bar
                ax.annotate(f"{v:.1f}", (bar.get_x() + bar.get_width() / 2, y_lbl),
                            xytext=(0, 4), textcoords="offset points",
                            ha="center", va="bottom", fontsize=TICK_FS,
                            color="white", bbox=label_bbox, zorder=6)
            y_top = max(y_top, hi, *heights)

        ax.set_xticks(x)
        ax.set_xticklabels(group_labels, fontsize=TICK_FS)
        ax.tick_params(axis="y", labelsize=TICK_FS)
        ax.grid(axis="y", alpha=0.20, zorder=0)
        ax.set_ylim(0, y_top * 1.18)

    draw_panel(ax_std, "std")
    ax_std.set_ylabel("Std Dev of Inter-Report Interval (µs)", fontsize=LABEL_FS)
    ax_std.set_title("Scheduling Jitter Under Background Stress, 2 kHz",
                     fontsize=TITLE_FS, fontweight="bold")
    ax_std.legend(fontsize=LEGEND_FS, loc="upper right", ncol=2)

    draw_panel(ax_p99, "p99")
    ax_p99.axhline(expected, color="#888888", linestyle="--", linewidth=1.2,
                   label=f"Ideal {int(expected)} µs", zorder=2)
    ax_p99.set_ylabel("p99 Interval (µs)", fontsize=LABEL_FS)
    ax_p99.set_title("p99 Tail Latency Under Background Stress, 2 kHz",
                     fontsize=TITLE_FS, fontweight="bold")
    ax_p99.legend(fontsize=LEGEND_FS, loc="upper right", ncol=3)

    fig.tight_layout(h_pad=2.5)
    cond_names = {"cpu": "CPU", "mem": "Memory", "combined": "Combined"}
    caption = "    ".join(f"{cond_names[c]}: {cmd}" for c, cmd in STRESS_PARAMS.items())
    caption += ("\nStress conditions are single captures; "
                "shaded bands show idle run-to-run range.")
    fig.text(0.01, -0.005, caption, ha="left", va="top",
             fontsize=TICK_FS, color="#BBBBBB", family="monospace")

    out = FIG_DIR / "stress_comparison.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("Saved figures/stress_comparison.png")

    # --- Stress stats table (stdout + markdown) ---
    headers = ["Condition", "Kernel", "n", "Reports", "Outliers",
               "Std", "p99", "p99.9", "Max", "Outside idle range?"]
    rows: list[list[str]] = []
    for kernel in kernels:
        name = "Preempt" if kernel == "preempt" else "Stock"
        runs = idle_runs[kernel]
        med  = {m: float(np.median([r[m] for r in runs]))
                for m in ("reports", "outliers", "std", "p99", "p999", "imax")}
        rows.append(["Idle (median)", name, str(len(runs)),
                     f"{med['reports']:,.0f}", f"{med['outliers']:,.0f}",
                     f"{med['std']:.2f}", f"{med['p99']:.2f}",
                     f"{med['p999']:.2f}", f"{med['imax']:.2f}", "—"])
        lo, hi = idle_range[kernel]["std"]
        for c in conds:
            s = stress[kernel][c]
            outside = "yes" if (s["std"] < lo or s["std"] > hi) else "no"
            rows.append([cond_names[c], name, "1",
                         f"{s['reports']:,}", f"{s['outliers']:,}",
                         f"{s['std']:.2f}", f"{s['p99']:.2f}",
                         f"{s['p999']:.2f}", f"{s['imax']:.2f}", outside])

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    sep = "=" * (sum(widths) + 2 * (len(widths) - 1))
    print(f"\nStress comparison, 2 kHz (\"Outside idle range?\" compares Std "
          f"against that kernel's idle min–max)\n{sep}")
    print("  ".join(h.ljust(w) if i < 2 else h.rjust(w)
                    for i, (h, w) in enumerate(zip(headers, widths))))
    print(sep)
    for r in rows:
        print("  ".join(v.ljust(w) if i < 2 else v.rjust(w)
                        for i, (v, w) in enumerate(zip(r, widths))))
    print(sep)
    for kernel in kernels:
        name = "Preempt" if kernel == "preempt" else "Stock"
        (slo, shi), (plo, phi) = idle_range[kernel]["std"], idle_range[kernel]["p99"]
        print(f"{name} idle range: std {slo:.2f}–{shi:.2f} µs, p99 {plo:.2f}–{phi:.2f} µs")
    print()

    md = ["# Stress Comparison, 2 kHz", "",
          "Idle rows are medians of 5 per-run values; stress rows are single 30 s captures.",
          "\"Outside idle range?\" compares Std against that kernel's idle min–max.", "",
          "| " + " | ".join(headers) + " |",
          "|" + "|".join(["---"] * 2 + ["---:"] * (len(headers) - 3) + [":---:"]) + "|"]
    md += ["| " + " | ".join(r) + " |" for r in rows]
    md += ["", "Idle run-to-run range (min–max of 5 runs):", ""]
    for kernel in kernels:
        name = "Preempt" if kernel == "preempt" else "Stock"
        (slo, shi), (plo, phi) = idle_range[kernel]["std"], idle_range[kernel]["p99"]
        md.append(f"- {name}: std {slo:.2f}–{shi:.2f} µs, p99 {plo:.2f}–{phi:.2f} µs")
    md += ["", "Stress parameters:", ""]
    md += [f"- {cond_names[c]}: `{cmd}`" for c, cmd in STRESS_PARAMS.items()]
    (FIG_DIR / "stress_stats.md").write_text("\n".join(md) + "\n")
    print("Saved figures/stress_stats.md")


# ---------------------------------------------------------------------------
# Figure 7 — same_kernel_comparison.png
# One kernel (6.6.123.2) booted in two dynamic preemption modes (full / none),
# so preemption mode is the only variable. The unit of analysis is the run:
# bars are medians of per-run values, dots are the runs, error bars min–max.
# A 2 s warmup-trimmed recomputation is reported in the tables only.
# Also writes figures/same_kernel_stats.md.
# ---------------------------------------------------------------------------
SAME_KERNEL_MODES = ("full", "none")
SAME_KERNEL_RUNS  = {"idle": 5, "cpu": 3, "mem": 3, "combined": 3}
WARMUP_INTERVALS  = 4000   # 2 s at 2 kHz
REJECTED_DIR      = REPO_ROOT / "data" / "rejected"


def plot_same_kernel_comparison() -> None:
    expected   = EXPECTED_US[2000]
    conds      = list(SAME_KERNEL_RUNS)
    cond_names = {"idle": "Idle", "cpu": "CPU", "mem": "Memory", "combined": "Combined"}
    mode_names = {"full": "Preempt full", "none": "Preempt none"}
    mode_color = {"full": KERNEL_COLOR["preempt"], "none": KERNEL_COLOR["stock"]}

    def run_path(mode: str, cond: str, i: int) -> Path:
        return DATA_DIR / f"2khz_{mode}_{cond}{i}.csv"

    # --- 1. Validation ---
    problems: list[str] = []
    releases: dict[str, list[str]] = defaultdict(list)
    for mode in SAME_KERNEL_MODES:
        for cond, n in SAME_KERNEL_RUNS.items():
            for i in range(1, n + 1):
                csv_path  = run_path(mode, cond, i)
                meta_path = csv_path.with_suffix(".meta.json")
                if not csv_path.exists() or not meta_path.exists():
                    problems.append(f"{csv_path.name}: CSV or .meta.json sidecar missing")
                    continue
                meta = json.loads(meta_path.read_text())
                if meta.get("syn_dropped_events") != 0:
                    problems.append(f"{meta_path.name}: syn_dropped_events = "
                                    f"{meta.get('syn_dropped_events')!r} (expected 0)")
                if meta.get("preempt_active") != mode:
                    problems.append(f"{meta_path.name}: preempt_active = "
                                    f"{meta.get('preempt_active')!r} (filename says {mode!r})")
                releases[meta.get("kernel_release", "<missing>")].append(csv_path.name)
    if len(releases) > 1:
        detail = "; ".join(f"{rel}: {len(files)} file(s), e.g. {files[0]}"
                           for rel, files in releases.items())
        problems.append(f"kernel_release differs across same-kernel files — {detail}")
    if problems:
        raise RuntimeError("Same-kernel capture validation failed:\n  " + "\n  ".join(problems))
    kernel_release = next(iter(releases))

    # --- 2. Per-run metrics (full capture and warmup-trimmed) ---
    def run_metrics(clean: np.ndarray, outliers: np.ndarray) -> dict:
        return dict(
            std=float(np.std(clean)),
            p99=float(np.percentile(clean, 99)),
            p999=float(np.percentile(clean, 99.9)),
            imax=float(np.max(clean)),
            outliers=len(outliers),
        )

    def load_trimmed(csv_path: Path) -> tuple[np.ndarray, np.ndarray]:
        # Same filtering as load_intervals(), applied after dropping the first
        # WARMUP_INTERVALS raw intervals so the cut is identical for every file.
        df = pd.read_csv(csv_path).sort_values("timestamp_s").reset_index(drop=True)
        iv = (df["timestamp_s"].diff().dropna() * 1_000_000).to_numpy()[WARMUP_INTERVALS:]
        ok = iv <= expected * OUTLIER_FACTOR
        return iv[ok], iv[~ok]

    runs:    dict[str, dict[str, list[dict]]] = {m: {} for m in SAME_KERNEL_MODES}
    trimmed: dict[str, dict[str, list[dict]]] = {m: {} for m in SAME_KERNEL_MODES}
    for mode in SAME_KERNEL_MODES:
        for cond, n in SAME_KERNEL_RUNS.items():
            runs[mode][cond], trimmed[mode][cond] = [], []
            for i in range(1, n + 1):
                p = run_path(mode, cond, i)
                clean, outliers, _ = load_intervals(p, expected)
                runs[mode][cond].append(run_metrics(clean, outliers))
                trimmed[mode][cond].append(run_metrics(*load_trimmed(p)))

    def vals(data, mode: str, cond: str, metric: str) -> list[float]:
        return [r[metric] for r in data[mode][cond]]

    # --- 3. Figure ---
    apply_dark_style()
    group_labels = [f"{cond_names[c]} (n={n})" for c, n in SAME_KERNEL_RUNS.items()]
    bar_width    = 0.35
    x            = np.arange(len(conds))
    label_bbox   = dict(boxstyle="round,pad=0.15", fc="black", alpha=0.6, ec="none")

    fig, (ax_std, ax_p99) = plt.subplots(2, 1, figsize=FIG_SIZE, dpi=DPI)
    fig.suptitle(f"Same Kernel ({kernel_release.split('-')[0]}), "
                 "Preemption Mode Only: 2 kHz",
                 fontsize=TITLE_FS, fontweight="bold")

    def draw_panel(ax, metric: str) -> None:
        y_top = 0.0
        for mi, mode in enumerate(SAME_KERNEL_MODES):
            offset = (mi - 0.5) * bar_width
            for ci, cond in enumerate(conds):
                v   = vals(runs, mode, cond, metric)
                med = float(np.median(v))
                lo, hi = min(v), max(v)
                xc  = x[ci] + offset
                ax.bar(xc, med, width=bar_width, color=mode_color[mode],
                       label=mode_names[mode] if ci == 0 else "_nolegend_", zorder=3)
                ax.errorbar(xc, med, yerr=[[med - lo], [hi - med]], fmt="none",
                            ecolor="white", elinewidth=1.4, capsize=6, zorder=4)
                ax.scatter(xc + np.linspace(-0.07, 0.07, len(v)), v, s=18, color="white",
                           edgecolors="black", linewidths=0.6, zorder=5)
                ax.annotate(f"{med:.1f}", (xc, hi), xytext=(0, 4),
                            textcoords="offset points", ha="center", va="bottom",
                            fontsize=TICK_FS, color="white", bbox=label_bbox, zorder=6)
                y_top = max(y_top, hi)
        ax.set_xticks(x)
        ax.set_xticklabels(group_labels, fontsize=TICK_FS)
        ax.tick_params(axis="y", labelsize=TICK_FS)
        ax.grid(axis="y", alpha=0.20, zorder=0)
        ax.set_ylim(0, y_top * 1.18)

    draw_panel(ax_std, "std")
    ax_std.set_ylabel("Std Dev of Inter-Report Interval (µs)", fontsize=LABEL_FS)
    ax_std.legend(fontsize=LEGEND_FS, loc="upper right")

    draw_panel(ax_p99, "p99")
    ax_p99.axhline(expected, color="#888888", linestyle="--", linewidth=1.2,
                   label=f"Ideal {int(expected)} µs", zorder=2)
    ax_p99.set_ylabel("p99 Interval (µs)", fontsize=LABEL_FS)
    ax_p99.legend(fontsize=LEGEND_FS, loc="upper right", ncol=3)

    fig.tight_layout(rect=[0, 0, 1, 0.97], h_pad=2.5)
    caption = "    ".join(f"{cond_names[c]}: {cmd}" for c, cmd in STRESS_PARAMS.items())
    caption += ("\nBars: median of runs. Dots: individual runs. "
                "Error bars: min–max across runs.")
    fig.text(0.01, -0.005, caption, ha="left", va="top",
             fontsize=TICK_FS, color="#BBBBBB", family="monospace")

    out = FIG_DIR / "same_kernel_comparison.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("Saved figures/same_kernel_comparison.png")

    # --- 5. Tables ---
    def fmt_table(headers: list[str], rows: list[list[str]], n_left: int = 2) -> tuple[str, str]:
        widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
        just   = lambda cells: "  ".join(c.ljust(w) if i < n_left else c.rjust(w)
                                         for i, (c, w) in enumerate(zip(cells, widths)))
        sep    = "=" * len(just(headers))
        text   = "\n".join([sep, just(headers), sep, *(just(r) for r in rows), sep])
        md     = "\n".join(["| " + " | ".join(headers) + " |",
                            "|" + "|".join(["---"] * n_left + ["---:"] * (len(headers) - n_left)) + "|",
                            *("| " + " | ".join(r) + " |" for r in rows)])
        return text, md

    def summary_rows(data) -> list[list[str]]:
        rows = []
        for cond in conds:
            for mode in SAME_KERNEL_MODES:
                s, p, p9 = (vals(data, mode, cond, m) for m in ("std", "p99", "p999"))
                idle_med = float(np.median(vals(data, mode, "idle", "std")))
                delta = ("—" if cond == "idle"
                         else f"{(np.median(s) - idle_med) / idle_med * 100:+.1f}%")
                rows.append([cond_names[cond], mode, str(len(s)),
                             f"{np.median(s):.2f}", f"{min(s):.2f}–{max(s):.2f}",
                             f"{np.median(p):.1f}", f"{min(p):.1f}–{max(p):.1f}",
                             f"{np.median(p9):.1f}", delta])
        return rows

    summary_headers = ["Condition", "Mode", "n", "Median std", "Std range",
                       "Median p99", "p99 range", "Median p99.9", "Δ median std vs idle"]

    def separation(data, cond: str, metric: str) -> str:
        f, n = vals(data, "full", cond, metric), vals(data, "none", cond, metric)
        if max(f) < min(n):
            return "full entirely below none"
        if max(n) < min(f):
            return "none entirely below full"
        return "ranges overlap"

    sep_rows = [[cond_names[c], m, separation(runs, c, mk), separation(trimmed, c, mk)]
                for c in conds
                for m, mk in (("std", "std"), ("p99", "p99"), ("p99.9", "p999"))]

    # Reject counts: accepted runs in data/raw plus rejected attempts in data/rejected.
    rej_pattern = re.compile(r"^2khz_(full|none)_(idle|cpu|mem|combined)\d+_attempt\d+$")
    rejects: dict[tuple[str, str], int] = defaultdict(int)
    if REJECTED_DIR.exists():
        for p in REJECTED_DIR.glob("*.csv"):
            m = rej_pattern.match(p.stem)
            if m:
                rejects[(m.group(1), m.group(2))] += 1
    rej_rows: list[list[str]] = []
    stress_totals = {mode: [0, 0] for mode in SAME_KERNEL_MODES}   # [rejects, accepted]
    for mode in SAME_KERNEL_MODES:
        for cond, accepted in SAME_KERNEL_RUNS.items():
            r = rejects[(mode, cond)]
            attempts = accepted + r
            rej_rows.append([mode, cond_names[cond], str(attempts), str(r),
                             f"{r / attempts * 100:.0f}%"])
            if cond != "idle":
                stress_totals[mode][0] += r
                stress_totals[mode][1] += accepted
    _, fisher_p = fisher_exact([stress_totals["full"], stress_totals["none"]])
    fr, fa = stress_totals["full"]
    nr, na = stress_totals["none"]
    fisher_line = (f"Fisher exact test, stress rejects full vs none "
                   f"({fr}/{fr + fa} vs {nr}/{nr + na}): two-sided p = {fisher_p:.4f}")

    t_a = fmt_table(summary_headers, summary_rows(runs))
    t_b = fmt_table(["Condition", "Metric", "Full capture", f"Warmup-trimmed"], sep_rows)
    t_c = fmt_table(summary_headers, summary_rows(trimmed))
    t_d = fmt_table(["Mode", "Condition", "Attempts", "Rejects", "Reject rate"], rej_rows)

    titles = [
        "a) Per-condition summary (per-run values; full 30 s captures)",
        "b) Separation check: run values of full vs none",
        f"c) Per-condition summary, warmup-trimmed (first {WARMUP_INTERVALS:,} intervals dropped)",
        "d) Reject counts (SYN_DROPPED captures in data/rejected/)",
    ]
    print(f"\nSame-kernel comparison, {kernel_release}, 2 kHz")
    for title, (text, _) in zip(titles, (t_a, t_b, t_c, t_d)):
        print(f"\n{title}\n{text}")
    print(fisher_line + "\n")

    md = [f"# Same-Kernel Comparison: Preemption Mode Only, 2 kHz", "",
          f"Kernel `{kernel_release}` booted with dynamic preemption `full` and `none`. "
          "Every value is computed per run; medians and ranges are across runs. "
          "Nothing is pooled across runs.", ""]
    for title, (_, table) in zip(titles, (t_a, t_b, t_c, t_d)):
        md += [f"## {title}", "", table, ""]
    md += [fisher_line, "", "Stress parameters:", ""]
    md += [f"- {cond_names[c]}: `{cmd}`" for c, cmd in STRESS_PARAMS.items()]
    (FIG_DIR / "same_kernel_stats.md").write_text("\n".join(md) + "\n")
    print("Saved figures/same_kernel_stats.md")


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
    plot_stress_comparison()
    plot_same_kernel_comparison()
    print_summary()
    print("Done. Figures written to figures/")
