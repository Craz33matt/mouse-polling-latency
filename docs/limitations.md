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

**Why the experiment is still valid:** Both the preemptive and stock kernel
captures run through the same usbipd layer. Since the passthrough overhead
is present in both conditions equally, it cancels out of the
*comparison between conditions*. The experiment measures the effect of
scheduling on timing consistency, not absolute device latency.

---

## 2. Kernel Preemption Level

The custom kernel used in preemptive captures reports:

preempt_status: none voluntary (full)

This is **voluntary preemption**, not full real-time preemption (`PREEMPT_RT`).
In voluntary mode the kernel yields at explicit yield points; it does not
forcibly interrupt running kernel threads the way a true RT kernel would.

**Consequence:** Any scheduling improvement measured here is a lower bound on
what full `PREEMPT_RT` would achieve. The effect of true RT preemption on
input timing would likely be larger.

**Why this was the limit:** WSL2 runs on a Microsoft-maintained kernel fork.
Full `PREEMPT_RT` patch series cannot be cleanly applied to the WSL2 kernel
without significant additional work. Voluntary preemption is the maximum
level practically achievable in this environment.

---

## 3. Timestamp Source: evdev, Not usbmon

Report timestamps are taken from the Linux **evdev** input layer
(`/dev/input/eventX`). The kernel stamps each event at the moment it enters
the input subsystem, before it reaches userspace — so Python's read latency
does not corrupt the intervals.

However, evdev sits several layers above the raw USB bus. The chain is:

USB wire → usbhid driver → input subsystem → evdev → our script

Timestamps reflect when the event reached the **input subsystem**, not when
it arrived on the USB wire. Processing time inside usbhid and the input
subsystem is included in the measured intervals.

**The rigorous alternative** would be `usbmon`, which timestamps at the USB
host controller level. This is identified as future work — it would require
parsing binary usbmon capture files and filtering for HID interrupt transfers,
but would give a truer picture of wire-level timing.

---

## 4. Device-Side Firmware: NDA Restriction

The OP1 8K V2 uses a **Nuvoton M483 MCU** and **PAW3950 optical sensor**.
The PAW3950 datasheet and register map are available only under NDA from
PixArt, making direct firmware inspection or modification impossible without
a commercial relationship.

**Consequence:** The device-side half of the latency pipeline — specifically
the synchronization between the sensor's internal scan rate and the USB
report rate — cannot be measured or modified at the firmware level. This
research addresses only the host-side scheduling path.

**Workaround identified:** A development board approach (STM32 or nRF52840
paired with a PMW3360, which has a public datasheet) would allow full
firmware access and device-side scan/report sync experiments. This is
identified as a future direction.

---

## 5. Two Separate Latency Problems

Input latency from mouse to game has two independent sources that are often
conflated:

**Host-side scheduling jitter** — after a report leaves the device, the OS
scheduler determines when the usbhid driver services it and when it reaches
the application. This is what kernel preemption affects, and what this
research measures.

**Device-side scan/report desync** — inside the mouse, the sensor samples
motion on its own clock (scan rate) independently of when the MCU ships USB
reports (report rate). If these are not synchronized, a report can carry 
outdated motion data before it ever leaves the device. No amount of host-side
preemption fixes this — it requires firmware-level synchronization. This is
what Wooting refers to as "True 8K" polling.

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

## Summary Table

| Limitation | Effect | Mitigated? |
|---|---|---|
| usbipd overhead | Raises absolute latency baseline | Yes — present in both conditions equally |
| Voluntary preemption only | Understates full RT effect | Documented — lower bound claim only |
| evdev timestamps, not usbmon | Misses intra-driver processing time | Documented — future work |
| PAW3950 NDA firmware | No device-side access | Documented — dev board identified as workaround |
| Human motion variability | Minor inter-run inconsistency | Minimized via consistent protocol |