# Cash and shares must agree at the allowed execution limit

2026-09-07. Follow-up to PR6. The first Fast value, Value and Model exit orders in round
`btc-updown-5m-1788757800` closed with `PAPER_NO_PROTECTED_DEPTH`. The screenshot identified
05:12:01 and05:12:03UTC. A read-only reconstruction found a sizing defect, not insufficient
simulated account balances. Each portfolio still hadUSD100 and each order reserved underUSD5.

## Recorded orders

| Strategy | Cash principal | Allowed price | Required shares | Cost at that price |
| --- | --- | --- | --- | --- |
| Fast value | 4.67 | 0.32 | 14.5938 | 4.670016 |
| Value | 4.67 | 0.34 | 13.7353 | 4.670002 |
| Model exit | 4.67 | 0.34 | 13.7353 | 4.670002 |

The pinned SDK rounds protected BUY shares upward. Our original quote looked affordable at
the better asks present during entry evaluation, so it missed the fact that the signed minimum
shares cost more than the signed cash when the ask reached the permitted limit. The simulator's
minimum-receipt rejection was correct. Disabling it or granting fractional free shares would
conceal a defect in constructing an executable order.

The previous repair only reduced the cash when the *current* book could not supply the rounded
minimum shares. This repair checks `minimum_receive * price_limit > principal` regardless of
current better prices, then uses the existing exact cash/share-grid calculation. Cash is reduced,
costs recomputed and the price cap retained. All four directional strategies share this path.
Pair order sizing is unchanged.

## Fixed-capture reconstruction

The read-only scratch replay is `limit-sizing/work/replay_first_orders.py`; results are in
`work/first-orders-replay.json`. It retains the original modeled values, quote inputs, order
activation times and price caps. It uses the first recorded Down book whose source and receipt
timestamps both follow simulated activation. These are captured books, not proof of the exact
exchange state at every unrecorded execution-engine read.

- Fast value: activation1788757921849ms; entry book event440842; execution book event440911,
  source1788757922525ms and received1788757922997ms. The best ask was0.32 for22.37shares.
- Value: activation1788757923892ms; entry book event440927; execution book event440963,
  source1788757924618ms and received1788757925047ms. Best ask0.34 for77.4shares.
- Model exit: activation1788757923985ms; the same entry/execution books as Value.

The original amounts reproduce all three unfilled results. Corrected amounts ofUSD4.66 for
14.5625shares at0.32 andUSD4.59 for13.5shares at0.34 fill in the reconstruction. These are
counterfactual fills. Historical orders, cash, losses, round-attempt counts and performance are
not rewritten, and the replay does not establish any subsequent profit.

## Consequences and verification

Actual principal can vary below the spending target because supported cash/share combinations
differ by price. At a0.71 limit, theUSD5 budget permitsUSD4.26 principal for6 protected shares;
the previousUSD4.67 requested an unaffordable6.5775 at that boundary. Required fees remain
reserved. A changed cash amount during final pre-post revalidation still rejects the old
prepared order; a looser limit with unchanged cash/reserve remains supported. No safety check
was relaxed to increase fills.

Ten new regression cases failed on the original source: seven full engine cases cover all
four modes and asks rising to their allowed limits, and three exercise actual pinned-SDK
signing without posting. After correction they pass. Additional cases retain rejection of
worse prices, inadequate depth and a deliberately malformed minimum share requirement.
Immediate simulated orders now retain execution-time book timestamps, best quotes, limit,
requested amount, available quantity and remaining amount in their existing paper measurements.
This lets later audits distinguish a real price/depth miss from a receipt-quantity mismatch.

Changing only account allocation fromUSD100 toUSD1,000 would not alter this defect because
theUSD5 order budget is separate. Increasing order size is a later liquidity/capacity experiment.
The current correction preserves both allocation and order-budget settings. Full verification
and continuous-service cutover evidence are recorded in [progress](../progress.md).
