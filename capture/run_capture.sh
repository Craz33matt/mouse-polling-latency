#!/usr/bin/env bash
# Usage: capture/run_capture.sh <idle|cpu|mem|combined> <output.csv>
set -euo pipefail
MODE=$1
OUT=$2

case "$MODE" in
  idle)     STRESS="" ;;
  cpu)      STRESS="--cpu 4" ;;
  mem)      STRESS="--vm 2 --vm-bytes 50%" ;;
  combined) STRESS="--cpu 4 --vm 1 --vm-bytes 50% --io 1" ;;
  *) echo "Unknown mode: $MODE"; exit 1 ;;
esac

if [ -e "$OUT" ]; then echo "Refusing to overwrite $OUT"; exit 1; fi
if [ ! -e /dev/input/event0 ]; then echo "Mouse not attached (no /dev/input/event0)"; exit 1; fi

sudo -v   # ask for the sudo password now, before stress starts

STRESS_PID=""
if [ -n "$STRESS" ]; then
  stress-ng $STRESS --timeout 45s >/dev/null 2>&1 &
  STRESS_PID=$!
  sleep 3
  if ! kill -0 "$STRESS_PID" 2>/dev/null; then echo "stress-ng failed to start"; exit 1; fi
  echo "stress-ng running: $STRESS"
fi

sudo ./venv/bin/python capture/capture_reports.py \
  --device /dev/input/event0 --duration 30 --out "$OUT"

if [ -n "$STRESS_PID" ]; then
  kill "$STRESS_PID" 2>/dev/null || true
  wait "$STRESS_PID" 2>/dev/null || true
fi
pkill -x stress-ng 2>/dev/null || true
