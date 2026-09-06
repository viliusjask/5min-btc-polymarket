# Final 35-minute public CLI capture

2026-09-06. This measured the actual installed native `btc5m observe` path with anonymous
public reads. It did not initialize an account, submit orders, simulate fills or estimate profit.

## Provenance and commands

- Source at process launch: `ac325751386af82757912bf1ed12e4944316b816`.
- Default configuration file SHA256: `f5705f5af4df93bda5b0b8e14c0dfa8ae9ffed65f5cebdfcaa3ceece2c11f77e`.
- Actual observation lifecycle: 19:22:04.834–19:57:04.885 UTC; process exited0 at about19:57:05.
- `stderr.txt` was empty; the journal records OBSERVE_STARTED and OBSERVE_COMPLETED.
- Output: ignored `work/final-observe-35m/`, with metadata, SQLite journal, stdout, report and summary.
- Full public report:34,719,467bytes, SHA256 `5e30fe4f22d9b6da22eb3fabc7d1e4428a1098da92dedfb201f99cb8165102a3`.

```bash
uv run --locked btc5m observe --duration 2100 --runtime work/final-observe-35m/ledger.sqlite
uv run --locked btc5m report --records --runtime work/final-observe-35m/ledger.sqlite
```

The Engine-only publication/calibration correction at2e83025 does not affect anonymous observe,
which records snapshots at publication and does not run Engine.step. Final integrated review
subsequently found live cache-invalidation, live cleanup and final-label reducer defects. The
capture contains no explicit final-reference conflicts, and it does not exercise funded execution
or run_live cleanup. Its successful exit is not evidence that those findings were already fixed.
They require their own regressions and independent rereview on the later source.

## Observed outcomes

| Measurement | Result |
|---|---|
| Public observations |23,675 |
| Complete snapshots / paired raw decisions |2,989 /5,978 |
| Spot / TWAP60 records |2,009 /2,010 |
| Book records |6,378 |
| Value screens with a probability estimate |175 across2 unique rounds |
| Momentum screens with a probability estimate |91 across1 unique round |
| Entry-eligible raw screens |0 in either mode |
| Captured opening boundaries |6 rounds |
| Captured boundaries later compared with official opening values |4; all agreed within the configured USD1e-8 tolerance |
| Official opening records, including initially missed boundaries |6 rounds |
| Official final-price records |5 rounds; no reported producer conflict |
| Calibration times reached / samples recorded |7 /7 within0–2seconds after the predeclared time |
| Samples with a probability estimate |1; its later official final label had not arrived by shutdown |
| Future calibration at capture end |1 pending; its target was19:58UTC, after the run ended |
| Metadata rejections with compared fields |169; expected tick0.001 versus actual0.01 |
| Stream-unavailable events |4, representing spot/TWAP timeout pairs at19:27:14 and19:46:57UTC |

The six earlier calibration samples contain two missing-reference and four insufficient-history
screens, so they are observed snapshots but not usable probability predictions. The one available
prediction was approximately71.94% Up at19:53:00.604UTC; value rejected PRICE_BAND and momentum
rejected MOMENTUM_MOVE. There is no completed prediction/outcome pair here from which to claim
calibration accuracy, much less strategy return.

The run began after the19:20 opening. The exact19:25 TWAP boundary was absent from received source
records, so its reference remained missing until official metadata arrived. The next six exact
boundaries were captured. Four delayed official comparisons differed only by approximately
USD1.8e-13 to4.6e-12, consistent with published numeric precision. Do not interpolate a missed
boundary or treat the success of these four comparisons as a guarantee about all future feeds.

Spot source-to-receipt delay was median2.587seconds,95th percentile3.161seconds; TWAP60 was
median2.680seconds,95th percentile3.235seconds. These include source delivery and any clock offset;
they are not an isolated exchange/network latency measurement. They support investigating aligned
faster information without changing the contract's actual settlement reference.

## Interpretation

The full publication, persistence, delayed metadata and report path operated for35minutes and
stopped cleanly. A zero-entry run is a valid observation: the configured policy found no qualifying
trade. Most of the run was the default30-minute history warm-up; afterward, available prices/moves
failed the entry criteria. This neither validates nor disproves profitability and is not a reason
to loosen thresholds to manufacture activity.

The earlier adapter/core capture had one value-eligible screen and motivated the experimental
information confirmation. This later CLI run is separate evidence. Its public observations also
contain the immutable initial six-minute sample used for the complementary-exit quote comparison;
that analysis's own hash and332-pair/642-direction denominator are recorded in the
[inventory ruling](inventory-strategy-ruling.md).
