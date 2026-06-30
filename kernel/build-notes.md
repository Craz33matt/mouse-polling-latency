# Preemptive Kernel Build Notes

## Kernel Details
- **Version:** 6.6.123.2-microsoft-standard-WSL2+
- **Branch:** linux-msft-wsl-6.6.y
- **Preemption model:** Full preemption — CONFIG_PREEMPT=y
- **Timer frequency:** CONFIG_HZ=250
- **Dynamic preemption:** CONFIG_PREEMPT_DYNAMIC=y (no runtime override applied)
- **Full config:** see kernel/config.txt

## Key Config Flags

```
CONFIG_PREEMPT=y
CONFIG_PREEMPT_BUILD=y
CONFIG_PREEMPT_COUNT=y
CONFIG_PREEMPTION=y
CONFIG_PREEMPT_DYNAMIC=y
CONFIG_PREEMPT_RCU=y
CONFIG_HZ=250
CONFIG_NO_HZ=y
# CONFIG_PREEMPT_NONE is not set
# CONFIG_PREEMPT_VOLUNTARY is not set
```


## Build Process
1. Cloned the Microsoft WSL2 kernel fork at branch linux-msft-wsl-6.6.y
2. Enabled full preemption via menuconfig (CONFIG_PREEMPT=y)
3. Compiled inside WSL2 Ubuntu with build-essential
4. Installed by pointing .wslconfig at the compiled bzImage:
[wsl2]
kernel=C:\path\to\bzImage
5. Restarted WSL2 with `wsl --shutdown` from Windows PowerShell

## Purpose
Built to reduce host-side scheduling jitter during high-rate USB HID
input capture. Full preemption allows urgent work (input event handling)
to interrupt lower-priority kernel threads faster and more consistently
than the stock WSL2 kernel's non-preemptive scheduler.

## Notes
- CONFIG_PREEMPT_RT (full real-time preemption) was not attempted —
  the PREEMPT_RT patch series does not apply cleanly to the Microsoft
  WSL2 kernel fork without significant additional porting work
- Runtime preemption mode was not overridden via boot parameter;
  compiled default (full) was used for all preemptive captures
- perf_event_paranoid = 2 (standard WSL2 restriction)