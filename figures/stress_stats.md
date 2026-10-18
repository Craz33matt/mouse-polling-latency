# Stress Comparison, 2 kHz

Idle rows are medians of 5 per-run values; stress rows are single 30 s captures.
"Outside idle range?" compares Std against that kernel's idle min–max.

| Condition | Kernel | n | Reports | Outliers | Std | p99 | p99.9 | Max | Outside idle range? |
|---|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| Idle (median) | Preempt | 5 | 59,999 | 0 | 17.14 | 532.00 | 669.00 | 836.00 | — |
| CPU | Preempt | 1 | 59,998 | 0 | 26.20 | 581.00 | 612.00 | 983.00 | no |
| Memory | Preempt | 1 | 59,999 | 0 | 18.80 | 565.00 | 596.00 | 825.00 | no |
| Combined | Preempt | 1 | 59,998 | 0 | 16.24 | 555.00 | 590.00 | 1206.00 | no |
| Idle (median) | Stock | 5 | 59,998 | 0 | 15.85 | 534.00 | 662.01 | 880.00 | — |
| CPU | Stock | 1 | 59,998 | 1 | 32.56 | 592.00 | 617.01 | 668.00 | yes |
| Memory | Stock | 1 | 59,999 | 0 | 17.11 | 559.00 | 593.00 | 665.00 | no |
| Combined | Stock | 1 | 59,987 | 1 | 22.77 | 572.00 | 603.00 | 1044.00 | yes |

Idle run-to-run range (min–max of 5 runs):

- Preempt: std 12.02–31.90 µs, p99 524.00–626.00 µs
- Stock: std 12.50–18.93 µs, p99 529.00–537.00 µs

Stress parameters:

- CPU: `stress-ng --cpu 4`
- Memory: `stress-ng --vm 2 --vm-bytes 50%`
- Combined: `stress-ng --cpu 4 --vm 1 --vm-bytes 50% --io 1`
