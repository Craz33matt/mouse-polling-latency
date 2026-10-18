# Same-Kernel Comparison: Preemption Mode Only, 2 kHz

Kernel `6.6.123.2-microsoft-standard-WSL2+` booted with dynamic preemption `full` and `none`. Every value is computed per run; medians and ranges are across runs. Nothing is pooled across runs.

## a) Per-condition summary (per-run values; full 30 s captures)

| Condition | Mode | n | Median std | Std range | Median p99 | p99 range | Median p99.9 | Δ median std vs idle |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Idle | full | 5 | 23.79 | 18.21–26.98 | 579.0 | 564.0–581.0 | 604.0 | — |
| Idle | none | 5 | 17.83 | 15.80–20.69 | 564.0 | 551.0–570.0 | 607.0 | — |
| CPU | full | 3 | 13.80 | 12.16–17.45 | 528.0 | 524.0–533.0 | 591.0 | -42.0% |
| CPU | none | 3 | 13.53 | 12.81–14.31 | 533.3 | 530.0–540.0 | 575.0 | -24.1% |
| Memory | full | 3 | 13.86 | 12.64–14.27 | 538.0 | 536.0–539.0 | 584.0 | -41.7% |
| Memory | none | 3 | 19.11 | 17.15–22.71 | 554.0 | 543.0–557.0 | 613.0 | +7.1% |
| Combined | full | 3 | 19.49 | 19.02–19.55 | 554.0 | 553.0–560.0 | 630.0 | -18.1% |
| Combined | none | 3 | 14.37 | 13.99–16.17 | 536.0 | 532.0–546.0 | 597.0 | -19.4% |

## b) Separation check: run values of full vs none

| Condition | Metric | Full capture | Warmup-trimmed |
|---|---|---:|---:|
| Idle | std | ranges overlap | ranges overlap |
| Idle | p99 | ranges overlap | ranges overlap |
| Idle | p99.9 | ranges overlap | ranges overlap |
| CPU | std | ranges overlap | ranges overlap |
| CPU | p99 | ranges overlap | ranges overlap |
| CPU | p99.9 | none entirely below full | ranges overlap |
| Memory | std | full entirely below none | full entirely below none |
| Memory | p99 | full entirely below none | full entirely below none |
| Memory | p99.9 | full entirely below none | ranges overlap |
| Combined | std | none entirely below full | none entirely below full |
| Combined | p99 | none entirely below full | none entirely below full |
| Combined | p99.9 | none entirely below full | ranges overlap |

## c) Per-condition summary, warmup-trimmed (first 4,000 intervals dropped)

| Condition | Mode | n | Median std | Std range | Median p99 | p99 range | Median p99.9 | Δ median std vs idle |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Idle | full | 5 | 23.70 | 18.20–26.84 | 579.0 | 564.0–581.0 | 603.1 | — |
| Idle | none | 5 | 17.20 | 15.66–20.26 | 564.0 | 551.0–569.0 | 597.0 | — |
| CPU | full | 3 | 12.80 | 10.87–16.37 | 525.0 | 523.0–530.0 | 577.0 | -46.0% |
| CPU | none | 3 | 13.20 | 12.35–13.73 | 532.0 | 529.0–538.0 | 567.0 | -23.3% |
| Memory | full | 3 | 13.40 | 12.36–14.00 | 536.0 | 535.0–538.0 | 579.0 | -43.5% |
| Memory | none | 3 | 17.88 | 16.27–21.83 | 549.0 | 541.0–553.0 | 597.0 | +3.9% |
| Combined | full | 3 | 18.91 | 18.61–19.20 | 553.0 | 552.0–558.0 | 625.0 | -20.2% |
| Combined | none | 3 | 13.53 | 13.30–15.45 | 534.0 | 531.0–542.0 | 587.0 | -21.3% |

## d) Reject counts (SYN_DROPPED captures in data/rejected/)

| Mode | Condition | Attempts | Rejects | Reject rate |
|---|---|---:|---:|---:|
| full | Idle | 5 | 0 | 0% |
| full | CPU | 3 | 0 | 0% |
| full | Memory | 3 | 0 | 0% |
| full | Combined | 3 | 0 | 0% |
| none | Idle | 5 | 0 | 0% |
| none | CPU | 4 | 1 | 25% |
| none | Memory | 4 | 1 | 25% |
| none | Combined | 4 | 1 | 25% |

Fisher exact test, stress rejects full vs none (0/9 vs 3/12): two-sided p = 0.2286

Stress parameters:

- CPU: `stress-ng --cpu 4`
- Memory: `stress-ng --vm 2 --vm-bytes 50%`
- Combined: `stress-ng --cpu 4 --vm 1 --vm-bytes 50% --io 1`
