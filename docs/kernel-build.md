# Kernel Build

This project uses one custom WSL2 kernel, 6.6.123.2-microsoft-standard-WSL2+.
The same binary is used for both preemption modes in the main experiment.
The build log is in [`kernel/build-notes.md`](../kernel/build-notes.md) and
the full configuration is in [`kernel/config.txt`](../kernel/config.txt).

## What the Build Changes and Why

The kernel is built from Microsoft's WSL2 kernel fork, branch
`linux-msft-wsl-6.6.y`. The one change made on purpose was the preemption
model: full preemption (`CONFIG_PREEMPT=y`) was enabled in menuconfig.

The aim was to reduce host-side scheduling jitter during high-rate USB HID
input capture. With full preemption, input event handling can interrupt
lower-priority kernel work at more points than a non-preemptive kernel
allows. The stock WSL2 kernel used in the earlier experiment
(6.18.33.1-microsoft-standard-WSL2) reports `CONFIG_PREEMPT_NONE=y` in its
capture metadata.

Preemption-related lines from `kernel/config.txt`:

```
CONFIG_PREEMPT_BUILD=y
# CONFIG_PREEMPT_NONE is not set
# CONFIG_PREEMPT_VOLUNTARY is not set
CONFIG_PREEMPT=y
CONFIG_PREEMPT_COUNT=y
CONFIG_PREEMPTION=y
CONFIG_PREEMPT_DYNAMIC=y
CONFIG_PREEMPT_RCU=y
```

Other settings in the same file that this project relies on:

| Setting | Value | Used for |
|---|---|---|
| `CONFIG_HZ` | 250 | Timer frequency, recorded in the build notes |
| `CONFIG_NO_HZ` / `CONFIG_NO_HZ_IDLE` | y | Tickless idle |
| `CONFIG_IKCONFIG_PROC` | y | Exposes `/proc/config.gz`, which the capture script reads for `preempt_compiled` |
| `CONFIG_DEBUG_FS`, `CONFIG_SCHED_DEBUG` | y | Expose `/sys/kernel/debug/sched/preempt`, used for `preempt_active` |
| `CONFIG_USBIP_VHCI_HCD` | m | The virtual host controller that usbipd forwards the mouse through |
| `CONFIG_USB_HID`, `CONFIG_INPUT_EVDEV` | m | The HID driver and the evdev interface the capture reads from |

PREEMPT_RT was not attempted. The PREEMPT_RT patch series does not apply
cleanly to the Microsoft WSL2 kernel fork without significant additional
porting work.

## Build and Install

1. Clone the Microsoft WSL2 kernel fork at branch `linux-msft-wsl-6.6.y`.
2. Enable full preemption in menuconfig (`CONFIG_PREEMPT=y`).
3. Compile inside WSL2 Ubuntu with build-essential.
4. Point `.wslconfig` on Windows at the compiled bzImage:

   ```
   [wsl2]
   kernel=C:\path\to\bzImage
   ```

5. Restart WSL2 with `wsl --shutdown` from Windows PowerShell.

## CONFIG_PREEMPT_DYNAMIC: One Binary, Two Modes

Because the kernel is built with `CONFIG_PREEMPT_DYNAMIC=y`, the preemption
mode can be chosen at boot instead of at compile time. The compiled default
is full. Passing `preempt=none` on the kernel command line boots the same
binary in none mode.

In WSL2 the kernel command line is set in `.wslconfig` on Windows:

```
[wsl2]
kernel=C:\path\to\bzImage
kernelCommandLine=preempt=none
```

Remove the `kernelCommandLine` line to go back to full mode, and run
`wsl --shutdown` after either change so WSL2 boots with the new setting.

For the earlier two-kernel experiment, no `preempt=` parameter was set, so
all of those preempt captures ran in the compiled default, full. The main
experiment's none-mode captures are the only ones booted with
`preempt=none`.

### Verifying the Active Mode

`/proc/config.gz` shows `CONFIG_PREEMPT=y` in both modes, because the
compiled config doesn't change. The active mode has to be read at runtime:

```bash
sudo cat /sys/kernel/debug/sched/preempt
```

The file lists the available modes and puts the active one in parentheses.
In full mode it reads `none voluntary (full)`. The word in parentheses is
the active mode. Reading it requires root.

Every capture records this automatically. `capture/capture_reports.py`
stores the word in parentheses as `preempt_active` in the capture's
`.meta.json`, along with `preempt_compiled` from `/proc/config.gz` and the
full `/proc/cmdline` as `kernel_cmdline`. In the main experiment, the none
mode metadata shows `preempt_active` as `none` and ends `kernel_cmdline`
with `preempt=none`. The full mode metadata shows `preempt_active` as
`full` and has no `preempt=` parameter. `analysis/plot_intervals.py` checks
`preempt_active` against the mode in each filename before analyzing anything.
