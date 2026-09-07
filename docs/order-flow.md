# Order-flow experiments

The **Experiments → Order flow and pair construction** study adds 17 independent USD100
paper wallets. The original six portfolios and original 84-variant study keep their
own histories. This is implemented research software; its settings are hypotheses,
and correlated variants are not independent evidence or additive profits.

## What is being tested

| Idea | Implementation and comparison |
| --- | --- |
| Book pressure selects the first pair leg | Two thresholds, 0.2 and 0.5, on the weighted top-20 Binance quantity imbalance. Require consecutive recorded observations spanning at least one second. Compare with Inventory pairs using the same quote lifetime and inventory timeout. Subsequent hedges retain the existing pair-cost limit. |
| Executed volume without price progress | Four absorption variants: 10/30-second windows and 0.3/0.6 normalized buying/selling imbalance. Fade the pressure only while the absolute price move stays within one basis point (0.01%). Four continuation controls instead require price progress in the flow direction. |
| Early pressure plus later confirmation | First common observation with both asks between 40¢ and 60¢, 20–60 seconds after opening. Record it once for both pressure thresholds and the control, even if pressure fails. At 90–120 seconds, require a three-cent increase in the chosen side. The control uses only that later price increase. No later replacement of an unfavorable early observation. |
| Compatible 5m/15m markets | Scanner only, during shared-expiry windows. Buy Up at the lower opening threshold and Down at the higher threshold; if both legs fill, the terminal sum pays at least USD1 per pair. Exact settlement source/rules, known anchors, depth, fees, protected limits and budget must pass. A quote candidate is not an order, fill or profit. |
| Split, sell, merge | Wait a simulated second, convert up to USD5 into equal outcome shares, and post passive sales. Initial sale floors sum to at least USD1 plus the pair edge; later quotes cannot lower those floors. Cancel on the existing time/inventory/order limits, wait for cancellation reconciliation, merge matched remnants, then reduce any unmatched side or await official settlement. |

Value and Fast value supply two additional controls. All variants retain existing
cash, trade-budget and loss guards. The daily entry-count cap remains disabled.
The directional flow variants use the existing protected order sizing and quote
checks; a directional signal is not itself a calibrated winning probability.

## Execution and evidence

Public Binance aggregate trades include executed quantity and aggressor direction.
Full top-20 snapshots arrive from the partial-depth stream. That stream provides no
exchange timestamp, so its freshness is explicitly measured from local receipt.
The shared input tape stores raw events, derived 10/30/60-second features, Polymarket
books and public trades. Flow warms up over its own short window after reconnection;
the existing settlement model still requires its separately validated history.

Resting orders fill only after observed, subsequent public flow exceeds the modeled
queue. Direct and complementary reports of one transaction cannot count twice.
The simulator supports passive sales as well as buys, delayed activation, partial
execution, cancellation grace, and uncertain transport intervals. Touching a quote
does not fill it. Public feeds cannot establish actual venue queue priority.

Splits and merges are atomic accounting conversions, not fake opening orders or
fills. Splitting USD5 creates five shares of each outcome and reduces cash by USD5.
Merging an equal remainder returns USD1 per pair. Each token receives half the
split cost for bookkeeping; that is not its fair value. Conversion requests, cash,
basis, fills and frame cursors survive replay restart. Fees are estimated for taker
fills; maker rebates and conversion gas costs are **excluded**, so split results
must not be treated as a net funded return. No SDK transaction path is involved.

The dashboard shows conversion records separately and uses passive sale orders as
the split variant's fill-rate denominator. Missing prices remain unavailable.
Queue uncertainty marks the round unsuitable for clean performance comparisons,
even when collector frames themselves arrived without a gap. All historical cash
records remain visible.

The study registers its parameters and implementation before running. After 288
full rounds it freezes up to three qualifying variants plus Value control for a
future 288-round test, using the existing evidence gate. Insufficient evidence
advances only Value. Restarting cannot reset cash or change registered parameters.

## Run and operate

No credentials are needed. Enable the extended recorder on the existing paper run:

```bash
btc5m paper --strategies all --continuous --capture-flow --config CONFIG --runtime RUNTIME
btc5m lab run --suite order-flow --continuous --config CONFIG \
  --source RUNTIME/capture.sqlite --runtime RUNTIME/order-flow-lab
```

The worker starts at the first recorded flow frame and excludes that partial round
from entry evaluation. It does not pretend older price-only history contains volume.

On this WSL installation, `btc5m-flow-lab.service` runs the new study; use
`systemctl --user status btc5m-flow-lab.service` and
`journalctl --user -u btc5m-flow-lab.service -n 50 --no-pager`.
Its runtime is `/home/vilius/.local/share/btc5m/paper-six-100-each/order-flow-lab`.
The collector and dashboard use `.worktrees/order-flow`. The original
`btc5m-lab.service` stays on `.worktrees/experiment-lab` because its registered
implementation must remain unchanged.

Reinstall with `scripts/install_paper_service.py --order-flow` and the existing
runtime/config/optional dashboard env-file paths. **Do not also pass `--lab` to
repoint the original registered study at changed code.** The installer enables
units; explicitly restart the collector/dashboard and start the new worker after
the prior journal owners stop. Keep both checkouts while services reference them.
No records are automatically pruned. The extra raw depth/trade data increases disk
usage; the existing low-space stop remains in force.

See the [implementation plan and sources](plans/order-flow.md),
[research lab methodology](experiment-lab.md), and [service recovery](paper-service.md).
