# Capture Tool

`capture_reports.py` records per-report timestamps from a USB mouse via the
Linux evdev input layer. Timestamps are stamped by the kernel at the moment
each event enters the input subsystem, so userspace read latency does not
corrupt the measured intervals. See `/docs/methodology.md` for the full
rationale.

## Setup

From the repo root:

```bash
source venv/bin/activate
pip install -r capture/requirements.txt
```

## Usage

List available input devices:

```bash
sudo ./venv/bin/python capture/capture_reports.py --list
```

Run a capture:

```bash
sudo ./venv/bin/python capture/capture_reports.py \
    --device /dev/input/eventN \
    --duration 30 \
    --out data/raw/CONDITION_NAME.csv
```

`sudo` is required because reading raw input devices needs elevated
permissions. Use `./venv/bin/python` directly rather than `python` —
calling `sudo python` drops the active virtual environment and will fail
with "command not found."

## Output

Each run produces two files:

- `<name>.csv` — one timestamp per report, in seconds (CLOCK_MONOTONIC)
- `<name>.meta.json` — device name, kernel version, preemption status,
  report count, and any dropped events (`SYN_DROPPED`)

A capture with any `SYN_DROPPED` events should be discarded and re-run —
dropped reports introduce gaps that corrupt the interval measurements
around them.

## Naming Convention

Output files follow `{polling_rate}khz_{kernel_type}.csv`, e.g.
`2khz_preempt.csv`, `1khz_stock.csv`. The filename is the experimental
label — name conditions consistently so the analysis script can key off
them correctly.

## Motion Protocol

Move the mouse in slow, continuous circles for the entire capture duration.
Start moving before launching the command. A stationary mouse sends no
reports; erratic motion produces inconsistent burst patterns. Consistent
slow circular motion gives the most representative steady-state intervals.