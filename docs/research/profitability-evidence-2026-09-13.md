# Evidence register for the profitability re-plan, September 13, 2026

This note collects the external and internal evidence behind
[the research plan](../plans/profitable-subset-research.md). Every number here is either a
public source, dated and linked, or a read-only reading of the persistent paper runtime at
the stated time. Nothing here establishes that any strategy is profitable.

## Venue facts rechecked today

| Item | Finding | Source |
|---|---|---|
| Settlement rule | The September 13 market resolves Up if the Chainlink BTC/USD 60-second TWAP over the range is at or above the price at the range start. The description states that spot markets are not the source. | Public Gamma API, event slug `btc-updown-5m-1789295700`, market 4493717 |
| Order constraints | Price tick 0.001, minimum order 5 shares, liquidity rewards require 50 shares within a 4.5-cent spread | Same Gamma record (`orderPriceMinTickSize`, `orderMinSize`, `rewardsMinSize`, `rewardsMaxSpread`) |
| Fees | `fee = C x feeRate x p x (1 - p)`; crypto taker `feeRate` 0.07; makers pay nothing | [Fee documentation](https://docs.polymarket.com/trading/fees) |
| Maker rebates | Only filled maker orders qualify; taker orders earn nothing. A per-market pool equal to 20% of crypto taker fees is split pro rata by each maker's fee-equivalent `C x feeRate x p x (1 - p)` of executed liquidity. Paid daily; at least USD 1 must accrue before a payout. Rechecked September 13 after the revision 1 review. | [Maker Rebates Program](https://docs.polymarket.com/programs/maker-rebates) |
| Recorded fee parameters | Every captured market so far records `fee_rate` 0.07 with exponent 1 | [Reversal evidence audit](reversal-evidence-audit.md) |

Consequence for H7: a maker's pro-rata share equals 20% of its own fee-equivalent only under
the assumption that every matching taker paid the crypto rate, so the plan treats that number
as an upper bound, applies it to passive fills only, and shows it against the USD 1 minimum.

The Gamma record also shows `makerBaseFee` and `takerBaseFee` of 1000. The bot does not use
those fields; it reads the CLOB fee parameters per market. The plan keeps that rule and treats
the Gamma fields as unexplained until compared with an actual fill.

## Published research found today

| Paper | What it reports | What it means here |
|---|---|---|
| Gruener, "Calibrated but Not Sharp: Stated Probabilities in Five-Minute Crypto Markets on Polymarket", SSRN 6863546, June 2026 | 14,808 BTC/ETH/SOL/DOGE five-minute contracts over sixteen days, logged at a fixed moment about one minute before close. Prices are calibrated (slope 1.01). The search summary adds that a costless rule "which side is ahead at the snapshot" called the final direction about 81% of the time against the market's 64%. | Calibration at T-60 means no free money from simply buying favorites there. The sharpness claim, if it holds, says the spot-versus-reference sign carries information the book has not priced. That is the hypothesis behind our momentum family and the new final-minute family. The full text is behind an access wall; only the abstract and a search summary were read. Treat the 81/64 figure as unverified until the paper is read. [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6863546) |
| Dai, Jia, Yu, "Settlement Manipulation in Prediction Markets", arXiv 2606.31675, June 30, 2026 | After the five-minute BTC contract launch (February 12, 2026), Binance net order flow jumps in the final ten seconds, about 3.9 times larger in near-even cycles; the spot price reverts by about a quarter within ten seconds in near-even cycles. About 1,600 cycles are classified as pushed. The identified cohort captured about USD 8.2M; retail accounts bore 93% of losses. Manipulation is largely absent in fifteen-minute contracts. The paper describes settlement as a Chainlink reading at close. | Two consequences. First, the venue's later move to a 60-second TWAP is consistent with a countermeasure, so results from the endpoint era do not transfer unchanged. Second, near-even rounds in the final minute carry adversarial flow; a policy that holds near-even inventory into settlement is exposed. The plan reports results split by settlement distance. [arXiv](https://arxiv.org/abs/2606.31675) |
| Shen, Jin, Wu, Wang, Chen, "The Ghosts of Polymarket: When Off-Chain Matches Meet On-Chain Reverts", arXiv 2606.16852, June 15, 2026 | 1,952,440 reverted transactions; 980,133 filled orders selectively reverted through nonce bump, balance drain, allowance revoke and proxy trap; more than 24.3% of filled orders reverted during peak hours. | A matched order is not a fill. The paper simulator already requires terminal evidence; any funded step must count reverted matches as a cost and a risk. No simulation of this exists in the repository; it is a live-stage measurement, recorded in the plan's risk register. [arXiv](https://arxiv.org/abs/2606.16852) |
| Qin, Yang, "Polymarket-v1 Database", arXiv 2606.04217, June 2026 | 1.20 billion trade records, 1.30 million markets, November 21, 2022 to April 28, 2026, first-generation exchange only, trades without books, CC BY 4.0 on Hugging Face. | Useful for aggressor-direction methodology, not for five-minute BTC books. Not adopted. [arXiv](https://arxiv.org/abs/2606.04217), [dataset](https://huggingface.co/datasets/TimeSeventeen/Polymarket-v1) |
| PMXT Polymarket order book archive v2 | Hourly Parquet books, price changes, trades and tick changes from 2026-04-13T19 UTC, CC BY 4.0, "every live asset", gaps described as rare. Coverage of five-minute BTC tokens is not stated. | A possible months-long book history for market-price-only rules. It carries no Chainlink opening reference, so spot-versus-reference rules cannot be replayed from it. A bounded probe is planned before any import. [Archive documentation](https://archive.pmxt.dev/docs/v2-data-overview) |
| Bailey, Borwein, Lopez de Prado, Zhu, "The Probability of Backtest Overfitting" (2015/2017) | Combinatorially symmetric cross-validation estimates how often the in-sample best configuration underperforms out of sample. | The plan implements this estimate in pure Python over the registered grid. [Paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) |

Earlier registers remain valid: [scientific strategy](scientific-strategy.md),
[trader sentiment](trader-sentiment.md), [historical data availability](historical-data-availability.md).

## Internal evidence as of today

Read-only readings of `/home/vilius/.local/share/btc5m/paper-six-100-each/` at about
10:45 UTC on September 13. No runtime file was modified.

- Archive size: `capture.sqlite` 11.4 GB, `observations.sqlite` 16.2 GB, tape high-water
  442,086 frames. Capture began September 7. The collector, dashboard and both lab workers
  are active user services (restarted 12:46 local today; not by this task).
- The directional lab report is dated **2026-09-10 11:42 UTC** at cursor 248,506 of
  442,086. The worker has processed 483 rounds (198 on September 7, 197 on September 8, 55
  on September 9, 33 on September 10) and is about three days behind the tape. Full-engine
  replay of 84 variants is slower than capture. The order-flow lab is current (cursor 441,904
  at 10:41 UTC).
- Both automatic holdout selections chose nothing: "insufficient evidence; control only".
  The Value control in the directional holdout (September 8 07:35 to September 9 07:35 UTC)
  completed two rounds for a net of USD -5.16; the order-flow holdout completed none.
- No registered variant has reached 30 clean completed rounds. Leading clean results in the
  exploratory phase: `momentum-settlement` USD +3.57 on 25 clean of 27 completed rounds;
  `momentum-20-90-150` USD +2.12 on 14 clean of 83 completed rounds (107 rounds uncertain);
  `reversal-60-1` USD +134.47 realized but USD -12.37 on 9 clean rounds.
- Uncertainty is policy dependent. Over the same 483 rounds, `momentum-settlement` (hold to
  settlement) has 14 uncertain rounds, while `momentum-20-90-150` (stop and target exits) has
  107. Gaps during the holding path flag exit policies; settlement-only policies need only a
  valid entry and an official label.
- Entry rates are low: 27 completed rounds in 483 observed for `momentum-settlement`, 83 for
  `momentum-20-90-150`. At those rates a 30-round clean sample needs weeks of capture per
  variant, and a 100-round holdout needs months.
- The probability model remains worse than the market at two minutes before close
  (Brier difference +0.0025 over 254 rounds in the directional study, +0.0036 over 519 in the
  order-flow study; positive means the market is better).

These readings define the plan's first problem: evidence throughput, not a shortage of ideas.

## Internal evidence after local-work recovery (September 13, 20:49 UTC reading)

Read-only readings taken by the revision 6 PLAN author after the ten history/storage commits
and the online-backup fix were merged (`1d3b4df`) and the interrupted dataset increment was
restored (`4fdc0e1`). No runtime file was modified; the four user services stayed running.

- Tape: `capture.sqlite` 11.7 GB, high-water **505,209** frames, first frame 2026-09-07
  07:26 UTC, last frame 2026-09-13 20:49 UTC, identity `580e84ec...`.
- Directional lab report: generated 2026-09-13 20:49 UTC but `as_of` **2026-09-10 12:57
  UTC** at cursor **255,554** of 505,239; 84 variants; the worker is now about 3.3 days behind
  the tape (it was 248,506 of 442,086 at the 10:45 UTC reading). The holdout phase
  `test-1a44ea4f216f` still holds only the Value control: 2 completed rounds, 0 clean, net
  USD -5.16.
- No variant has 30 clean completed rounds. Leaders by clean rounds (exploratory phase, all
  from pinned implementations, not comparable as a portfolio): `momentum-settlement` 27 clean
  of 29 completed (14 uncertain), clean net USD +5.69, realized USD +6.76;
  `momentum-20-90-150` 15 clean of 85 completed (108 uncertain), clean net USD +1.57, realized
  USD -5.92; `momentum-30-90-150` 14 clean of 63 (88 uncertain), clean net USD -0.30. Every
  other variant has 12 or fewer clean rounds.
- External history: the September 4 OutcomeTick release (markets, books, best bid/ask, last
  trade price, Chainlink spot and TWAP60 CSVs) and the Binance `BTCUSDT-aggTrades-2026-09-04`
  ZIP (checksum verified) are downloaded under the runtime's `history/` directory with dated
  download manifests. Two conversion attempts on September 8 exist under
  `history/imported/`: one `failed` with `KeyboardInterrupt`, one left in status
  `converting` with partial tape files. **No completed external tape exists.** The importer's
  publication rule (a failed or interrupted import never publishes) held. These directories
  are user-owned runtime artifacts and are not touched by this plan; any new import writes to
  a fresh destination outside the runtime.
- Storage migration artifacts from September 8 (`storage-migrations/20260908-compact-v1/`)
  exist; they concern the observations journal, not the capture tape the dataset layer reads.
