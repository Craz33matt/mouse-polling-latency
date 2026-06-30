# Methodology

## Experiment Design

This experiment tests one independent variable: kernel preemption model
(`CONFIG_PREEMPT=y` vs `CONFIG_PREEMPT_NONE=y`). All other variables are
held constant across conditions: same device, same USB port, same polling
rate per paired comparison, same capture duration (30 seconds), same motion
protocol, same measurement tool and script version.

The dependent variable is the inter-report interval: the time in microseconds
between consecutive evdev `SYN_REPORT` events. The metric of primary interest
is the standard deviation of this interval, which measures scheduling jitter
directly. Tail percentiles (p95, p99, p99.9) are secondary metrics that
capture worst-case behavior.

Five runs per condition per rate (n=5) were collected to distinguish
reproducible findings from single-capture noise. All five runs are pooled
for distribution and percentile figures. Individual runs are shown separately
in the per-run consistency figure to verify that results are stable across
runs.

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
driver and input subsystem, not just the scheduling delay. This means the
measured intervals are an upper bound on scheduling jitter rather than a
precise measurement of it. This limitation is documented in
[`docs/limitations.md`](docs/limitations.md).

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
reported in the stats table. Any capture with a nonzero SYN_DROPPED count
was discarded before analysis.