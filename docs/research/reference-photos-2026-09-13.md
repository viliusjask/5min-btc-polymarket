# Reference photo inspection, September 13, 2026

The user supplied ten phone screenshots in the ignored local directory `.local/` as project
inspiration. This register records what each image shows, whether the idea was already
handled in earlier research, what was independently checked, and the decision. Raw images
are not copied into the repository. File names are the user's; content summaries are ours.
All ten files opened and were legible; none was unreadable.

Decision codes: **accept** (already implemented or adopted), **test** (registered as a
hypothesis in [the research plan](../plans/profitable-subset-research.md)), **defer**
(needs an unavailable prerequisite), **reject** (out of scope or unverifiable and not useful).

| File | Visible source | What it claims | Prior coverage | Decision |
|---|---|---|---|---|
| `VuKZUhPe.jpg` | X post by @igus_ai ("gus"), translated from Spanish | Took an open-source GitHub bot, tweaked it in Claude Code, USD 250 became USD 13,000; USD 600 after the first night | Historical: [trader evidence](trader-sentiment.md), [upstream assessment](upstream-assessment.md) | reject the return claim; accept the mechanism only as the baseline below |
| `SvBga7VA.jpg` | Continuation of the same post | Rule: wait until about two minutes before the round closes; require a USD 70 to 100 BTC move in the round; buy with the move at 0.80 to 0.99; "cover just a small part of the position only if the market gets too imbalanced". The parenthetical example is cut off by the reply bar; only "(e.g. 95/5)" is partly visible on a second look on September 13. Neither the hedge trigger nor its size is stated | Historical: the `momentum` comparator implements a modified version; the literal rule is not registered | test the no-hedge rule as the "screenshot literal (approximation)" baseline (B2 in the plan); defer the hedge variant because its trigger and size are undefined |
| `5K48FChw.jpg` | Continuation: link to `github.com/Novals83/5min-...`, a PowerShell log, a quoted @MikuBTC video, dated 05 Sep 26, 164K views | Log rows show fills at 0.81 to 0.96 settling at 1.00 with the sizes 260, 201, 137, 225, 48, 82 and 50 shares; one row reads "book flipped 95/5 -> micro-hedge -1.69" on the 48-share 0.81 fill. That single row is the only quantitative trace of the hedge (a USD 1.69 cost on a USD 38.88 position, about 4%) | Historical: the upstream repository was audited; its tracked code cannot place the shown orders | reject as evidence; the log is not a trade export and the repository lacks the runner |
| `Cs8y9ttZ.jpg` | X post by @Dan1ro0 ("Daniro"), 21h old at 21:24 local | "Grok Bot" harvests BTC volatility, USD 2,701 a day, USD 40,522 after 4,127 predictions, 11 setups an hour, six agents; buy Up and Down at different times so the pair costs under 100 cents | Historical: [inventory ruling](inventory-strategy-ruling.md); `passive_pairs`/`inventory_pairs` implemented | accept as implemented; test only the maker-rebate sensitivity (H7) |
| `hnvzzqwv.jpg` | Continuation | Paired = min(Qup, Qdown); the remainder stays directional while "agents still see an edge"; account AdanaKebab, 4,127 predictions, 52% win rate, three largest wins about USD 2,000 each | Historical: the September 6 check found about USD 40,352 venue profit at AdanaKebab; strategy attribution unverified | accept as implemented; no new mechanism |
| `EMSBUVWN.jpg` | X post by @0xboan ("boan"), 19h old | Funded "Grok Bot" with 0 ETH on Robinhood; 0 to 2.31 ETH in 24 hours; it launches fresh tokens and "collects its cut off every trade against them, win or lose for the buyer" | New | reject |
| `qg8QEf1H.jpg` | Continuation | 82% win rate, balance flat for two hours at hour eight, "fee income never stopped", one evening setup, a dashboard screenshot | New | reject |
| `R8zPrPEz.jpg` | X post by @Argona0x, 1d old | "STAMPEDE" watches wallets on Robinhood Chain launchpads; USD 100 to 2,640 in 41 minutes; a runner is a herd of wallets leaving one coin and entering the next; counts 54 wallets making the same move in 8 minutes | New | reject the venue; test the one transferable feature (wallet breadth, H6f) if archived trades carry a trader identifier |
| `a-JU3iOe.jpg` | Continuation | The video is "a recorded replay of one real hour at 20x"; "three of those back to back" gives USD 1,839,000 | New | reject |
| `C9OMqXbN.jpg` | X post by @harrychow_ | Hiring a USD 300K intern for Pinetree Research; apply by building with the Solari SDK | New | reject; not a trading idea |

## What was independently checked

- The current five-minute BTC market on September 13 (`btc-updown-5m-1789295700`, Gamma market
  4493717) still resolves on the Chainlink BTC/USD 60-second TWAP against the price at the start
  of the range. The bot's settlement model therefore still matches the live rule. Gamma also
  reports a 0.001 price tick, a 5-share minimum order, and liquidity rewards needing 50 shares
  within a 4.5-cent spread. Rewards are irrelevant to a USD 5 trade budget.
- Polymarket's fee page still states `fee = C x feeRate x p x (1 - p)` with crypto `feeRate`
  0.07, zero maker fees and a daily maker rebate of 20% of collected fees. A third-party article
  claims 25%; the official page is used. [Fee documentation](https://docs.polymarket.com/trading/fees).
- Grok Bot is a real SpaceXAI agent product and Robinhood Chain went live on July 1, 2026
  per public coverage. The memecoin profit claims in the boan and Argona posts have no wallet
  identifier, no trade export and no independent record. They were not verified. The boan
  mechanism (launch tokens, take a cut from buyers "win or lose") is not a trading strategy
  we can evaluate or should copy.
- The gus post's claimed return remains unverified, as on September 6. The @MikuBTC video
  and the 164K view count are audience numbers, not trading records.
- The Daniro figures in the new screenshots (USD 40,522 after 4,127 predictions) are
  consistent with the September 6 venue check (about USD 40,352). A 52% per-prediction win
  rate with positive total profit is consistent with a paired-inventory or maker account; it
  says nothing about whether a USD 5 taker bot can obtain the same fills.

## What is new since September 6

The only new trading content is the memecoin material (boan, Argona), which concerns a
different chain, different instruments and, in boan's case, a fee-extraction mechanism rather
than a forecast. The BTC-specific ideas (gus rule, Daniro pairing) were already assessed and
implemented in modified form. The two useful residues are:

1. Register the literal gus rule as a baseline so the modified `momentum` rule is compared
   with the idea that motivated it, not only with the market.
2. Treat maker economics (zero fee plus rebate) as a sensitivity scenario for the pairing
   strategies, because the AdanaKebab statistics fit a maker profile better than a taker one.
   The rebate applies only to filled maker orders and is a pro-rata share of a per-market
   pool; the plan's H7 credits it on passive fills only.

The gus hedge ("cover a small part ... e.g. 95/5") has no defined trigger or size in either
photo, so it is deferred rather than guessed. The plan records one bounded interpretation
for a possible later trial and labels the no-hedge baseline an approximation.

Neither residue is evidence of profitability. See the plan for how they are tested.
