#!/usr/bin/env python3
"""
capture_reports.py

Records per-report timestamps from a USB mouse via the Linux evdev layer.
Each mouse report ends in a SYN_REPORT event; we store the KERNEL-supplied
timestamp of that event. Because the kernel stamps the time when the event
is generated (not when we read it), our slower userspace loop does not
corrupt the interval measurements -- events wait in the kernel buffer with
their original timestamps intact.

Timestamps use CLOCK_MONOTONIC so an NTP step can't distort intervals.

Usage:
    python capture_reports.py --list
    python capture_reports.py --device /dev/input/eventN \
        --duration 20 --out ../data/raw/8khz_preempt.csv
"""

import argparse
import json
import platform
import time
from pathlib import Path

import evdev
from evdev import ecodes


def list_devices():
    devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
    if not devices:
        print("No input devices. Is the mouse attached to WSL via usbipd?")
        return
    print("Available input devices:")
    for d in devices:
        print(f"  {d.path:20s}  {d.name}")


def read_preempt_status():
    """Read kernel preemption model from compiled config."""
    try:
        import subprocess
        result = subprocess.run(
            ['zcat', '/proc/config.gz'],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if line == 'CONFIG_PREEMPT=y':
                return 'full (CONFIG_PREEMPT=y)'
            if line == 'CONFIG_PREEMPT_VOLUNTARY=y':
                return 'voluntary (CONFIG_PREEMPT_VOLUNTARY=y)'
            if line == 'CONFIG_PREEMPT_NONE=y':
                return 'none (CONFIG_PREEMPT_NONE=y)'
            if 'CONFIG_PREEMPT' in line and 'not set' not in line and line.startswith('CONFIG_PREEMPT='):
                return line.strip()
    except Exception:
        pass
    try:
        with open('/sys/kernel/debug/sched/preempt') as f:
            return f.read().strip()
    except Exception:
        return 'unknown - check /proc/config.gz'


def capture(device_path, duration_s, out_path):
    dev = evdev.InputDevice(device_path)

    # Ask the kernel to timestamp with CLOCK_MONOTONIC, not CLOCK_REALTIME.
    import fcntl, struct
    EVIOCSCLOCKID = 0x400445A0
    fcntl.ioctl(dev.fd, EVIOCSCLOCKID, struct.pack("i", time.CLOCK_MONOTONIC))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    timestamps = []
    drops = 0
    print(f"Capturing from '{dev.name}' for {duration_s}s.")
    print("MOVE THE MOUSE CONTINUOUSLY (small circles) the whole time...")

    deadline = time.monotonic() + duration_s
    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_SYN:
                if event.code == ecodes.SYN_REPORT:
                    timestamps.append(event.timestamp())   # kernel monotonic ts
                elif event.code == ecodes.SYN_DROPPED:
                    drops += 1
            if time.monotonic() >= deadline:
                break
    except KeyboardInterrupt:
        print("\nInterrupted early.")

    # keep the raw data RAW: one timestamp per line, intervals computed later
    with open(out_path, "w") as f:
        f.write("timestamp_s\n")
        for t in timestamps:
            f.write(f"{t:.9f}\n")

    meta = {
        "device_name": dev.name,
        "device_path": device_path,
        "kernel_release": platform.release(),
        "preempt_status": read_preempt_status(),
        "duration_requested_s": duration_s,
        "report_count": len(timestamps),
        "syn_dropped_events": drops,
        "capture_unix_time": time.time(),
    }
    meta_path = out_path.with_suffix(".meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nWrote {len(timestamps)} reports -> {out_path}")
    print(f"Metadata -> {meta_path}")
    if drops:
        print(f"\n*** WARNING: {drops} SYN_DROPPED events. The kernel buffer "
              f"overflowed and reports were lost -- this capture's intervals "
              f"are NOT trustworthy. Re-run with a shorter --duration. ***")


def main():
    ap = argparse.ArgumentParser(description="Capture mouse report timestamps via evdev.")
    ap.add_argument("--list", action="store_true", help="list input devices and exit")
    ap.add_argument("--device", help="input device path, e.g. /dev/input/event5")
    ap.add_argument("--duration", type=float, default=20.0, help="capture seconds")
    ap.add_argument("--out", help="output CSV path")
    args = ap.parse_args()

    if args.list:
        list_devices()
        return
    if not args.device or not args.out:
        ap.error("--device and --out are required (or use --list)")
    capture(args.device, args.duration, args.out)


if __name__ == "__main__":
    main()
