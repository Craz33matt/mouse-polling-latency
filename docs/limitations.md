# Limitations & Known Constraints

This document describes the boundaries of what this research can and cannot
claim. Naming these limits is deliberate and part of how this research was designed.

---

## 1. WSL2 USB Passthrough Overhead

Mouse reports are forwarded from Windows to the WSL2 kernel via **usbipd**,
which tunnels USB traffic over a virtual network interface (vhci_hcd). This
forwarding layer introduces its own timing overhead and jitter on top of
whatever the device and host kernel contribute.

**Consequence:** Absolute latency numbers measured here are not representative
of native Linux latency. The baseline is higher than bare-metal by an unknown
and variable amount.

**Why the experiment is still valid:** Every capture, in both preemption modes
and both kernels, runs through the same usbipd layer. Since the passthrough
overhead is present in all conditions, it cancels out of the
*comparison between conditions*. The experiment measures the effect of
scheduling on timing consistency, not absolute device latency.

---

## 2. Kernel Preemption Level

The custom kernel was compiled with:

`CONFIG_PREEMPT=y`

This is **full preemption**, the strongest preemption level achievable in
the WSL2 environment short of `PREEMPT_RT`. With full preemption enabled,
the kernel can interrupt lower-priority threads at almost any point to
service higher-priority work such as input event handling. The same kernel
also has `CONFIG_PREEMPT_DYNAMIC=y`, which is what lets the main experiment
boot it in none mode with `preempt=none`.

Older captures stored a single `preempt_status` field. Early on it
reported "none voluntary (full)", which was read at the time as an error
from a permission-denied path. That string is the normal format of
`/sys/kernel/debug/sched/preempt`: it lists the available modes and puts the
active one in parentheses, so it showed full mode active. Captures now record
`preempt_compiled`, `preempt_active` and `kernel_cmdline` separately (see
[methodology.md](methodology.md)).

**Consequence:** This is a lower bound on what `PREEMPT_RT` would achieve,
but a stronger baseline than voluntary preemption.

**Why PREEMPT_RT was not used:** The `PREEMPT_RT` patch series does not
apply cleanly to the Microsoft WSL2 kernel fork without significant
additional porting work. Full preemption (`CONFIG_PREEMPT=y`) is the
maximum level practically achievable in this environment.

---

## 3. Timestamp Source: evdev, Not usbmon

Report timestamps are taken from the Linux **evdev** input layer
(`/dev/input/eventX`). The kernel stamps each event at the moment it enters
the input subsystem, before it reaches userspace, so Python's read latency
does not corrupt the intervals.

However, evdev sits several layers above the raw USB bus. The chain is:

USB wire → usbhid driver → input subsystem → evdev → our script

Timestamps reflect when the event reached the **input subsystem**, not when
it arrived on the USB wire. Processing time inside usbhid and the input
subsystem is included in the measured intervals.

**The rigorous alternative** would be `usbmon`, which timestamps at the USB
host controller level. This is identified as future work. It would require
parsing binary usbmon capture files and filtering for HID interrupt transfers,
but would give a truer picture of wire-level timing.

---

## 4. Device-Side Firmware: NDA Restriction

The OP1 8K V2 uses a **Nuvoton M483 MCU** and **PAW3950 optical sensor**.
The PAW3950 datasheet and register map are available only under NDA from
PixArt, making direct firmware inspection or modification impossible without
a commercial relationship.

**Consequence:** The device-side half of the latency pipeline, specifically
the synchronization between the sensor's internal scan rate and the USB
report rate, cannot be measured or modified at the firmware level. This
research addresses only the host-side scheduling path.

**Workaround identified:** A development board approach (STM32 or nRF52840
paired with a PMW3360, which has a public datasheet) would allow full
firmware access and device-side scan/report sync experiments. This is
identified as a future direction.

---

## 5. Two Separate Latency Problems

Input latency from mouse to game has two independent sources that are often
conflated:

**Host-side scheduling jitter.** After a report leaves the device, the OS
scheduler determines when the usbhid driver services it and when it reaches
the application. This is what kernel preemption affects, and what this
research measures.

**Device-side scan/report desync.** Inside the mouse, the sensor samples
motion on its own clock (scan rate) independently of when the MCU ships USB
reports (report rate). If these are not synchronized, a report can carry
outdated motion data before it ever leaves the device. No amount of host-side
preemption fixes this. It requires firmware-level synchronization.

This research addresses problem 1 only. Problem 2 is documented here for
completeness and identified as the primary motivation for the firmware
exploration in this repo.

---

## 6. Motion Protocol Variability

Captures were taken by moving the mouse in continuous slow circles for the
capture duration. Human motion is not perfectly consistent between runs,
which introduces minor variability in report patterns (a still mouse sends
no reports; burst motion sends clustered reports). This is an inherent
limitation of using a real input device rather than a signal generator.

Slow, continuous circular motion was chosen to minimize this effect and
produce the most representative steady-state inter-report intervals.

---

## 7. usbipd Throughput Cap at High Polling Rates

At the 8kHz device polling setting, the observed report rate through the
usbipd virtual USB layer was far below 8kHz: the 8kHz capture recorded
39322 reports in 10.0 s (`data/raw/8khz_preempt.meta.json`). This
indicates the vhci_hcd forwarding layer saturates at roughly the 4kHz level
for HID interrupt transfers.

**Consequence:** Captures labeled `8khz_*` reflect a device setting of 8kHz
but an observed rate near the 4kHz level. The 8kHz capture is reference only.

**Native Linux would not have this limitation.** Direct USB controller
access removes the forwarding layer entirely and is identified as the
correct environment for true 8kHz measurement.

---

## 8. Capture Order

In each preemption mode, all idle runs were captured first, then the CPU,
memory and combined runs in that order. None mode was captured in an
earlier session than full mode, and the three none-mode captures that had to
be re-run were taken at the end of that session.

**Consequence:** Time in the session is confounded with condition. Anything
that drifts over a session (host background activity, thermal state, the
way the mouse is being moved) would look like a difference between idle and
stress. This matters most for the finding that load reduced jitter, since
every idle run came before every stress run.

**Fix for future runs:** Interleave the conditions within each session, and
alternate which mode is captured first.

---

## 9. Small n and Multiple Comparisons

Each stress condition has 3 runs per mode, and idle has 5. With 3 runs per
side, the two modes' runs fall into completely separate ranges about 10% of
the time by chance alone. The separation table compares 12 metric and
condition pairs, so a few complete separations are expected from noise even
if preemption mode has no effect.

**Consequence:** The memory stress separation (favoring full) and the
combined stress separation (favoring none) are reported but not claimed as
effects. Detecting a small effect would need more runs per condition.

---

## 10. Rejected Captures

Captures with any `SYN_DROPPED` event were rejected and re-run. In the main
experiment, all three rejects came from none mode under stress (0/9 stress
attempts rejected in full mode, 3/12 in none mode). A Fisher exact test gives
a two-sided p = 0.2286.

**Consequence:** The accepted none-mode stress runs are the ones that did
not drop events. If dropped events go with heavier scheduling delays, those
accepted runs could understate none mode's jitter under stress. The rejected
files are kept in `data/rejected/` so this can be checked, but their intervals
are not analyzed.

---

## 11. Kernel Version Confound (Resolved)

The earlier experiment compared a custom 6.6.123.2 kernel with full
preemption against a stock 6.18.33.1 kernel with no preemption. Those differ
in version, build config and drivers as well as preemption, so a difference
between them could not be attributed to preemption.

**Resolution:** The main experiment boots one kernel binary in both modes
using dynamic preemption, so version and build are identical and only the
preemption mode changes. The two-kernel results are kept as supplementary
material only.

---

## Summary Table

| Limitation | Effect | Mitigated? |
|---|---|---|
| usbipd overhead | Raises absolute latency baseline | Yes, present in all conditions equally |
| Full preemption only, not PREEMPT_RT | Understates full RT effect | Documented, lower bound claim only |
| evdev timestamps, not usbmon | Misses intra-driver processing time | Documented, future work |
| PAW3950 NDA firmware | No device-side access | Documented, dev board identified as workaround |
| Human motion variability | Minor inter-run inconsistency | Minimized via consistent protocol |
| usbipd throughput cap | 8kHz setting yields a rate near the 4kHz level | Documented, native Linux identified as fix |
| Capture order | Time in session confounded with condition | No, future runs should interleave |
| Small n, multiple comparisons | Separations can arise from noise | Documented, no separation claimed as an effect |
| Rejected captures | Accepted none-mode stress runs may be a filtered set | Documented, rejects kept in `data/rejected/` |
| Kernel version confound | Earlier two-kernel comparison not attributable to preemption | Yes, resolved by the same-binary experiment |
