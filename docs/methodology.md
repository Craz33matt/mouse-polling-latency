# Methodology

## Experiment Design

### Main experiment: same binary, two preemption modes

The main experiment tests one independent variable: the kernel's active
preemption mode, full or none. It uses a single kernel binary
(6.6.123.2-microsoft-standard-WSL2+) for both modes, so kernel version, build
config and drivers are identical. All other variables are held constant
across conditions: same device, same USB port, same 2 kHz polling rate, same
capture duration (30 seconds), same motion protocol, same measurement tool
and script version.

Within each mode there are four load conditions: idle (5 runs) and three
stress-ng loads (3 runs each).

| Condition | Command |
|---|---|
| CPU | `stress-ng --cpu 4` |
| Memory | `stress-ng --vm 2 --vm-bytes 50%` |
| Combined | `stress-ng --cpu 4 --vm 1 --vm-bytes 50% --io 1` |

The parameters are identical in both modes. They are defined once in
`STRESS_PARAMS` in `analysis/plot_intervals.py`, which prints them in the
figure caption.

The dependent variable is the inter-report interval: the time in microseconds
between consecutive evdev `SYN_REPORT` events. The metric of primary interest
is the standard deviation of this interval, which measures scheduling jitter
directly. Tail percentiles (p99, p99.9) are secondary metrics that capture
worst-case behavior.

### Earlier experiment: two kernel versions

The earlier experiment compared a custom 6.6.123.2 kernel built with
`CONFIG_PREEMPT=y` against the stock 6.18.33.1 WSL2 kernel with
`CONFIG_PREEMPT_NONE=y`, at 1, 2 and 4 kHz with five idle runs per condition,
plus one capture per stress load at 2 kHz. Because the kernels differ in
version as well as preemption, this comparison is confounded. It is kept as
supplementary material, and the same-binary design above replaced it.

## Dynamic Preemption and How the Active Mode Is Verified

The custom kernel is built with `CONFIG_PREEMPT_DYNAMIC=y`. The compiled
default is full preemption (`CONFIG_PREEMPT=y`), and the mode can be changed
at boot with the `preempt=` kernel parameter. Full mode captures were taken
with no `preempt=` parameter. None mode captures were taken with
`preempt=none` on the kernel command line.

Since the compiled config is the same in both modes, `/proc/config.gz` alone
cannot tell them apart. Each capture's `.meta.json` records three fields:

- `preempt_compiled`: the preemption model line from `/proc/config.gz`
  (e.g. `CONFIG_PREEMPT=y`).
- `preempt_active`: the active mode read from
  `/sys/kernel/debug/sched/preempt`. That file lists the available modes
  with the active one in parentheses, such as `none voluntary (full)`, and the
  capture script stores the word in parentheses. Reading it needs root, which
  the capture already has. If it can't be read, the field is `unknown`.
- `kernel_cmdline`: the contents of `/proc/cmdline`, which shows whether
  `preempt=none` was set.

`preempt_status` is also written with the same value as `preempt_active`, for
older analysis code.

Before analyzing anything, `analysis/plot_intervals.py` checks every file in
the main experiment. Each must exist, have zero `SYN_DROPPED` events, have a
`preempt_active` that matches the mode in its filename, and share one
`kernel_release` with every other file. Any failure stops the script with a
message naming the file.

## Capture Procedure

Captures in the main experiment were taken with `capture/run_capture.sh`. For
a stress condition, it starts stress-ng in the background, waits, confirms
the process is still alive, and only then starts the 30-second capture. It
refuses to overwrite an existing output file, checks that the mouse is
attached, and kills stress-ng on exit even if the capture fails. This replaced
pasting commands by hand, which had twice run them out of order. See
[`capture/README.md`](../capture/README.md) for usage.

## Per-Run Analysis

The unit of analysis is the run. For each run the analysis computes std, p99,
p99.9, max and outlier count from that run's intervals alone. Summary tables
report the median across runs and the lowest-to-highest range, and the
figure shows every run as a dot. No headline number is pooled across runs.

For each condition and metric, a separation check compares the run values of
the two modes. It reports "full entirely below none", "none entirely below
full", or "ranges overlap".

## Warmup Trim

As a sensitivity check, every per-run metric is recomputed after dropping
the first 4,000 intervals (2 seconds at 2 kHz) of every run. The cut is
applied to the raw intervals before outlier filtering, so it is identical for
every file. The trimmed results appear only in the tables in
`figures/same_kernel_stats.md`, to show whether any conclusion depends on
startup transients.

## Rejected Captures

A capture with any `SYN_DROPPED` event is rejected and re-run. Rejected
files are moved to `data/rejected/` and renamed with an `_attempt{N}` suffix.
Their intervals are never analyzed. They are kept so the reject count per
mode and condition can be reported, and the analysis counts attempts as
accepted runs plus rejected files. A Fisher exact test compares total stress
rejects between the two modes.

## Why evdev and Not usbmon

Two options exist for timestamping mouse reports in Linux.

**usbmon** timestamps at the USB host controller level, as close to the wire
as the kernel allows. It captures the moment a USB interrupt transfer
completes at the HCI driver.

**evdev** timestamps at the input subsystem boundary. The kernel stamps each
`SYN_REPORT` event with `CLOCK_MONOTONIC` the moment it enters the input
layer, before it reaches any userspace reader.

This project uses evdev for two reasons. First, usbmon requires parsing binary
transfer logs and filtering for HID interrupt IN transfers, which adds
implementation complexity and its own potential for measurement error. Second,
and more importantly, evdev is where the scheduling effect being measured
actually appears: the gap between a USB interrupt completing and the kernel
reaching the evdev layer is exactly the scheduling delay that kernel preemption
is meant to reduce. usbmon would miss this delay entirely.

The tradeoff is that evdev timestamps include processing time inside the usbhid
driver and input subsystem in addition to the scheduling delay. This means the
measured intervals are an upper bound on scheduling jitter rather than a
precise measurement of it. This limitation is documented in
[`docs/limitations.md`](limitations.md).

## Why CLOCK_MONOTONIC

The capture script sets the evdev clock source to `CLOCK_MONOTONIC` via the
`EVIOCSCLOCKID` ioctl before reading any events. `CLOCK_MONOTONIC` is immune
to NTP steps and wall-clock adjustments, which can introduce discontinuities
into inter-report intervals if `CLOCK_REALTIME` (the default) is used.

## Motion Protocol

The mouse was moved in slow continuous circles for the full 30-second capture
duration. Motion began before the capture command was issued to avoid
initialization transients at the start of the interval sequence. The mouse was
never stopped during capture.

This protocol was chosen because the OP1 8K uses motion-gated reporting:
reports are only generated when the sensor detects a nonzero motion delta.
A stationary mouse produces no reports. Continuous slow circular motion
produces a steady, representative stream of reports at the configured polling
rate with minimal burst-motion artifacts.

## Outlier Handling

Inter-report intervals exceeding 3x the expected interval for a given polling
rate are classified as outliers and excluded from distribution and percentile
calculations. These represent either SYN_DROPPED gaps that escaped the
per-capture drop check, or usbipd forwarding stalls. They are counted and
reported in the stats tables. Any capture with a nonzero SYN_DROPPED count
was discarded before analysis.
