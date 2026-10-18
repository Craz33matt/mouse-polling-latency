# Data

Every capture is a pair of files: a CSV with one kernel timestamp per report
(column `timestamp_s`, seconds, `CLOCK_MONOTONIC`) and a `.meta.json` sidecar
with the device, kernel release, preemption mode, report count and
`SYN_DROPPED` count. Intervals are computed later by
`analysis/plot_intervals.py`. The CSVs stay raw.

## raw/

Accepted captures. Three naming schemes are in use.

### Same-binary experiment (main result)

`2khz_{mode}_{condition}{run}.csv`

- `mode` is the active dynamic preemption mode: `full` or `none`.
- `condition` is `idle`, `cpu`, `mem` or `combined`.
- `run` is the run number: 1 to 5 for idle, 1 to 3 for each stress condition.

Example: `2khz_none_mem2.csv` is the second memory stress run with the kernel
booted in none mode. All of these come from kernel
6.6.123.2-microsoft-standard-WSL2+, and their metadata includes
`preempt_compiled`, `preempt_active` and `kernel_cmdline`.

### Earlier two-kernel experiment, idle

`{rate}khz_{kernel}{run}.csv`

- `rate` is 1, 2, 4 or 8.
- `kernel` is `preempt` (custom 6.6.123.2, full preemption) or `stock`
  (6.18.33.1, no preemption).
- Run 1 has no number, so `2khz_preempt.csv` is run 1 and `2khz_preempt3.csv`
  is run 3.

### Earlier two-kernel experiment, stress

`2khz_{kernel}_stress_{condition}.csv`, with `condition` one of `cpu`, `mem`
or `combined`. These are single captures, one per kernel per condition, using
the same stress-ng commands as the main experiment.

## rejected/

Captures discarded because they recorded at least one `SYN_DROPPED` event.
They are named after the run they were meant to fill, with an attempt number:
`2khz_{mode}_{condition}{run}_attempt{N}.csv`. For example,
`2khz_none_cpu3_attempt1.csv` was the first attempt at none-mode CPU run 3,
and the accepted `raw/2khz_none_cpu3.csv` is the re-run.

Rejects are kept rather than deleted so the reject rate per mode and
condition can be reported. The analysis counts them but never analyzes their
intervals, because dropped events leave gaps that corrupt the intervals
around them.
