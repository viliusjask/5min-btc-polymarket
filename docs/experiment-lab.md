# Strategy experiment lab

The lab implements the five research priorities in [the plan](plans/experiment-lab.md).
It consumes the six-portfolio collector's exact public input recording. Each registered
variant has an independent $100 paper wallet, the configured fixed trade budget ($5 in the
installed run), and the existing loss guards. It never constructs an account client or sends
venue orders. The original six portfolios retain their own balances and journals.

## What runs

| Family | Default variants | Question |
|---|---:|---|
| Existing directional controls | 4 | How do Momentum, Value, Fast Value and Model Exit behave on the same recorded inputs? |
| Momentum lead and timing | 30 | Leads $10–$100 in $10 steps, across 60–120, 90–150 and 120–180 seconds remaining |
| Value surplus and timing | 12 | Required cost-adjusted surplus of 0, 1, 2 or 4 cents across those three windows |
| Model sensitivity | 4 | Change the adverse reference shift, or use the central probability instead of the conservative scenario floor |
| Exit rules | 14 | For Momentum and Value: 4/12/20-cent stops, no stop, time-only, settlement-only and model-based exits |
| Feed and execution delay | 4 | Value and aligned Fast Value with 750/1500ms simulated delays, against their existing 250ms controls |
| Normalized opening lead | 4 | Divide the opening-price move by expected remaining volatility |
| Recent continuation/reversal | 12 | Follow or oppose the actual previous 10/30/60-second move, at two normalized thresholds |

Total: **84 registered trials**. Some settings have identical economics to a control and many
share signals; 84 trials do not mean 84 independent sources of evidence. An explicit new-study
`--dense` option uses every integer Momentum lead from $1 to $100, giving 354 trials. Start coarse:
the larger search takes more resources and increases the chance of selecting noise.

Passive and inventory pairing continue in the original six-portfolio run. This lab focuses
on the directional pricing, timing and execution hypotheses; it does not add a second passive
queue simulator. Results from different variants must not be added into a combined portfolio.

## Dashboard and interpretation

Open the existing dashboard and choose **Experiments** next to Paper and Real. The page contains
a clickable Momentum parameter map, all registered variants, filters, equity charts, forecast
diagnostics, a signal/order/fill funnel, rejection reasons and the latest 50 orders per variant.
Export downloads the displayed lab report. Switching views cannot authorize trading.

- **Realized profit** is recorded cash profit from sells and simulated settlement; **usable
  completed profit** excludes incomplete rounds and rounds with an observed execution-data gap.
  Both remain visible. Exclusion can itself bias a sample, so inspect the uncertain count and
  raw results before interpreting a ranking.
- **Equity** is cash plus held contracts valued at observed bid depth, after estimated selling
  fees. Missing full depth produces a missing mark. Drawdown is the largest observed drop from
  an earlier peak; missing marks may conceal larger losses. Small remaining positions may be
  impossible to sell at the venue minimum even when there is displayed depth.
- An eligible screen must still survive a newer-price confirmation and execute against later
  protected depth. Acknowledgment, a stop trigger and a price touch are not fills.
- Forecasts are taken once per round, 120 seconds before settlement, at most two seconds late.
  **Brier loss** is squared probability error; **log loss** penalizes confident mistakes more
  strongly. Lower is better. Central-vs-market and fast-vs-central differences use matching
  rounds with verified official labels. Reliability bins compare predicted and observed Up
  frequency. Their small-sample intervals are descriptive, not proof of significance.
- Conservative scenario floors are sensitivity assumptions, not calibrated confidence bounds.
  The lab measures model calibration; it does not silently fit new probabilities to the same
  data used to report returns. Missing observations and labels stay explicit.

## Exploration and future testing

The first partial recorded round is excluded from trading. After 288 full rounds (24 hours),
the registered selection rule considers up to three variants with positive usable completed
profit, at least 30 usable completed rounds, and no unresolved rounds in that selection window.
It always includes the Value control. If none qualify, only that control advances and the
selection is marked insufficient evidence. Thirty rounds is an operating threshold, not a
statistical power calculation or proof that the strategy works.

Selection freezes parameter IDs, code identity, input high-water mark and a future start time.
The selected variants receive fresh $100 wallets for the **next** 288-round test. A holdout is
later data kept out of parameter selection. It starts after both the selection's wall-clock
time and all recorded inputs already available, even if the worker was catching up. Exits and
official-label reconciliation continue for positions opened before its end. Exploration also
continues, but does not change the frozen test. There is no automatic promotion to funded use.

Do not tune against a viewed holdout and continue calling it untouched evidence. Register a new
study/test when revising the hypothesis. The UI exposes all attempted variants, daily profit
blocks and sample counts; it does not manufacture annualized Sharpe ratios from a few hours.

## Commands

The collector creates `capture.sqlite` in its existing paper runtime. The lab runs separately:

```bash
.venv/bin/btc5m lab run --continuous \
  --source /home/vilius/.local/share/btc5m/paper-six-100-each/capture.sqlite \
  --runtime /home/vilius/.local/share/btc5m/paper-six-100-each/lab \
  --config /home/vilius/.config/btc5m/paper.toml
```

Omit `--continuous` to catch up to the current tape and stop. An existing study resumes its
registered settings; explicit incompatible settings are rejected. For a separate new study,
`--dense` expands the Momentum grid and `--explore-rounds` sets a 12–2016-round selection window.
The main dashboard reads the `lab/report.json` under its paper runtime; scratch studies elsewhere
can be inspected with `lab report --runtime PATH` without replacing that displayed study.

To manually freeze one to eight registered IDs for a future test:

```bash
.venv/bin/btc5m lab freeze --runtime /home/vilius/.local/share/btc5m/paper-six-100-each/lab \
  --variants REGISTERED_ID,ANOTHER_REGISTERED_ID --test-rounds 288
```

Manual tests remain registered alongside the automatic test. This command never changes a
previous phase or makes its entries retroactive.

The service installer accepts `--lab` once capture.sqlite exists. It enables
`btc5m-lab.service` alongside the collector/dashboard, with automatic restart and a watchdog:

```bash
systemctl --user status btc5m-paper.service btc5m-dashboard.service btc5m-lab.service
journalctl --user -u btc5m-lab.service -n 50 --no-pager
systemctl --user restart btc5m-lab.service
```

## Persistence and operating limits

For selected historical dates and variants, use the separate
[historical replay workflow](historical-replay.md). The
[public archive description](research/archive-capture.md) identifies the additional events
retained prospectively, and the [availability research](research/historical-data-availability.md)
explains which older external sources exist and why a price chart alone cannot replay fills.

`capture.sqlite` stores exact public source/receipt times, books, price histories and as-received
official labels. Shared ticks are deduplicated. Frames are compressed and checksummed. SQLite
WAL/FULL commits retain completed input transactions; checksums detect frame damage, not malicious
tampering or every possible storage fault. Unresolved label identities survive restart. Recovery
polling prioritizes the original holdings and rotates the remaining backlog within six slots.
An unavailable result after restart does not erase a previously observed official result.

`lab/study.json` registers configurations and source/code identity; `study.sqlite` records forecasts
and phases. The lab refuses a different tape, changed registered configuration or changed semantic
code. Upgrading code requires a deliberately new study directory while preserving the old study;
do not delete the manifest to bypass this check.

Variant journals are derived caches using WAL/NORMAL. A frame's orders, fills, cash, pending
confirmation and cursor commit atomically. Abrupt death rolls back the unfinished frame. Power
loss may discard a completed cache suffix, which is recomputed from the FULL input tape. Other
variants and the study cursor may be ahead; recovery starts at the earliest surviving cursor and
does not rescore old forecasts. No funded/live journal uses this cache durability mode.

SIGTERM stops between frames and saves a final report. Systemd restarts failures. A PC cannot
record markets while asleep, offline or off: missing observations are not reconstructed, and
affected execution remains visibly uncertain. The dashboard shows stale reports and input lag.
The original [WSL startup and recovery constraints](paper-service.md) still apply.

Nothing automatically deletes history. The lab checks a 512MiB free-space reserve; the collector
has its own 256MiB reserve. These are safeguards, not disk quotas. Check disk usage for long runs
and use SQLite online backups, or stop all owners before copying their full runtime directories.
Deleting the tape removes the basis for cache recovery. Disk failure requires independent backups.

This remains simulated execution. Recording cadence limits latency precision. Market impact,
queue priority, rebates, gas and actual redemption delay are not established by this lab. Official
labels allow zero-cost simulated payouts. The [research register](research/experiment-lab.md)
records primary sources and the limits of each inference.
