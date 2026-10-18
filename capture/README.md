# Capture Tool

`capture_reports.py` records per-report timestamps from a USB mouse via the
Linux evdev input layer. Timestamps are stamped by the kernel at the moment
each event enters the input subsystem, so userspace read latency does not
corrupt the measured intervals. See [`docs/methodology.md`](../docs/methodology.md)
for the full rationale.

`run_capture.sh` wraps one capture, and starts and verifies stress-ng when
the condition needs it. Use it for every capture.

## Setup

From the repo root:

```bash
source venv/bin/activate
pip install -r capture/requirements.txt
```

stress-ng must be installed for the stress conditions (`sudo apt install stress-ng`).

## run_capture.sh

```bash
capture/run_capture.sh <idle|cpu|mem|combined> <output.csv>
```

Example:

```bash
capture/run_capture.sh cpu data/raw/2khz_none_cpu1.csv
```

What it does, in order:

1. Checks that it got exactly two arguments and a known mode, and prints the
   usage line otherwise.
2. Changes to the repo root, so it works from any directory. Because of
   this, the output path is read relative to the repo root.
3. Refuses to run if the output file already exists, or if the mouse is not
   attached at `/dev/input/event0`.
4. Runs `sudo -v` so the password prompt happens before any load starts.
5. For a stress mode, starts stress-ng in the background with a 45 s timeout,
   waits 3 s, and exits with an error if stress-ng is no longer running.
6. Runs a 30 s capture with `capture_reports.py`.
7. Stops stress-ng. An exit trap also kills every stress-ng process if the
   capture fails, so load never keeps running after the script ends.

| Mode | stress-ng arguments |
|---|---|
| `idle` | none |
| `cpu` | `--cpu 4` |
| `mem` | `--vm 2 --vm-bytes 50%` |
| `combined` | `--cpu 4 --vm 1 --vm-bytes 50% --io 1` |

The script assumes the mouse is `/dev/input/event0`. Check with `--list`
below if that changes.

## capture_reports.py

List available input devices:

```bash
sudo ./venv/bin/python capture/capture_reports.py --list
```

Run a capture directly:

```bash
sudo ./venv/bin/python capture/capture_reports.py \
    --device /dev/input/eventN \
    --duration 30 \
    --out data/raw/CONDITION_NAME.csv
```

`sudo` is required because reading raw input devices needs root
permissions, and reading the active preemption mode from debugfs also needs
root. Use `./venv/bin/python` directly rather than `python`. Calling
`sudo python` drops the active virtual environment and will fail with
"command not found."

## Output

Each run produces two files:

- `<name>.csv`: one timestamp per report, in seconds (CLOCK_MONOTONIC)
- `<name>.meta.json`: device name, kernel release, preemption mode
  (`preempt_compiled`, `preempt_active`, and `preempt_status` as a legacy
  copy of `preempt_active`), `kernel_cmdline`, report count, and any dropped
  events (`SYN_DROPPED`)

A capture with any `SYN_DROPPED` events should be moved to `data/rejected/`
with an `_attempt{N}` suffix and re-run. Dropped reports introduce gaps that
corrupt the interval measurements around them.

## Naming Convention

Name files as described in [`data/README.md`](../data/README.md). For the
same-binary experiment that is `2khz_{mode}_{condition}{run}.csv`, e.g.
`2khz_full_idle3.csv`. The filename is the experimental label, and the
analysis checks the mode in the filename against `preempt_active` in the
metadata.

## Motion Protocol

Move the mouse in slow, continuous circles for the entire capture duration.
Start moving before launching the command. A stationary mouse sends no
reports; erratic motion produces inconsistent burst patterns. Consistent
slow circular motion gives the most representative steady-state intervals.
