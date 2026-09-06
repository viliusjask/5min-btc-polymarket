# Standalone BTC five-minute experiment design

Date: 2026-09-06. Upstream inspected: 1c9aa81ec64cdf62895b155ed64dc8e88c013102.
The user authorizes research, design, implementation, branch/worktree setup and independent
review. Routine decisions are delegated for this run. Funded orders, wallet approvals and
transfers are not part of development. The intended next step is a separate-wallet experiment
with approximately USD100, not an Alpha-Sentry integration or a promised return.

## Evidence and choice

The source register is in docs/research/scientific-strategy.md,
docs/research/trader-sentiment.md and docs/research/execution-design.md. The academic studies
supply hypotheses at different horizons, not coefficients for a two-minute BTC forecast.
Positive and negative trader accounts both lack complete reproducible datasets in the sources
inspected. Their concrete failures inform tests: fills, fees, stops, anchors and restarts.

We considered repairing only the original threshold rule, adding a transparent conditional
valuation, and making markets with passive orders. Implement the first two as explicit
strategy modes with shared execution and measurement. Defer passive orders and fitted
momentum/reversal models: fill selection and training need separate evidence. Do not add a
language-model decision layer, neural models, automatic compounding, or a micro-hedge.

The default candidate is `value`; `momentum` is a modified upstream reference comparison,
not a literal reproduction of the screenshot price band. Neither is validated. Older trader
studies generally predate TWAP60 settlement; their execution lessons transfer, not their
measured reversal frequencies or strategy profitability.
The value candidate estimates terminal probability under a zero-drift local normal model.
It screens entry prices; it DOES NOT model the expected return of the early-exit policy.
Every report calls its metric `terminal_surplus_proxy`, never expected trading profit.
A complete, realistic fill simulator is not a prerequisite for a small authorized live test.
The public `observe` command records real data and decisions without inventing paper profits.

## Contract and price model

Support only current BTC five-minute Up/Down CTF markets with known Chainlink BTC/USD TWAP60
resolutionSource, Up-on-equality rules, exact current slug, tokens, condition, 300-second round,
active/accepting state, tick size, minimum shares and live fee schedule. Parse round start from
the slug and validate eventStartTime/endDate; Gamma startDate is the listing date.
Unknown rules, changed fee schema, negative-risk markets or ambiguous token mapping reject entry.

The opening reference must be same-slot official eventMetadata.priceToBeat, or an exact
source-timestamp TWAP60 boundary point under a documented, empirically checked boundary policy.
Record provenance and later compare it with official metadata. Missing boundary data means skip,
not interpolation, first-received substitution or reuse of the previous round's reference.
The anonymous probe on 2026-09-06 verified two boundaries, including one whose neighboring
seconds differed. Enable exact captured-boundary anchors by default for this supported rule;
retain the explicit setting to require official metadata only. Compare later metadata with an
absolute USD0.00000001 tolerance for JSON-number rounding. This is a measured initial policy,
not proof of every future round: missing exact ticks still skip and mismatches pause entries.
Persist anchor status (official, boundary, missing, conflict), source timestamp when known,
fetch time and endpoint/query provenance. Use get_event(include_chat=False) with bounded retries;
this is an observed working route, not a cache-invalidation guarantee. Cached null cannot erase
an existing official anchor; any later conflicting official value pauses that round. Require
active/accepting booleans in the parser, never default them true. Mutable trading parameters
come from current CLOB reads, not cached Gamma metadata.

Collect Chainlink spot AND TWAP60 from the official RTDS through the unified SDK. Keep full
Decimal values and source/receive times. Connection deadlines use monotonic elapsed time;
wall-clock UTC is reserved for market boundaries and reports. Unknown stream kinds reject data. Raw spot history estimates raw volatility; smoothed
TWAP changes must not be used in a raw-price formula. Streams resume after disconnect but have
no history replay. Gaps invalidate the relevant warm-up/anchor. No Binance substitute.

Initial new-entry window is 60..180 seconds before expiry, inclusive. We deliberately avoid
new entries during the ending-average window. Let entry_tau=end-now determine the entry window, and model_tau=end-spot.source_time
condition the forecast on when the last spot was actually observed. Recheck entry_tau immediately
before POST. For model_tau>=60 seconds, zero drift and raw-dollar volatility sigma per sqrt(second):

    p_up = NormalCDF((spot - reference) / (sigma * sqrt(model_tau - 40)))

The 40 follows the conditional variance of a 60-second future arithmetic average; it is not
an empirically fitted coefficient. Exact discrete feed construction remains model uncertainty.
Use five-second sampled spot differences, time-based variance sum(delta_price**2)/elapsed,
with 300-second and 1800-second windows. Build five-second UTC source-time grid points;
choose the last observation at or before each grid point only if its age is <=2 seconds.
Each accepted grid point must use a distinct source observation. Skip isolated unavailable grid
points without interpolation or forward-fill; require at least95% of requested grid points and a
maximum12-second gap between accepted source observations. At five-second spacing with two-second
timing tolerance, this permits one missing grid but rejects two consecutive missing grids. Derive
variance denominator from actual accepted timestamps, not an assumed tick count. Required span
may fall short by at most the2-second sampling tolerance; missing endpoints therefore still reject.
These completeness bounds were selected from anonymous feed-availability evidence, not trading PnL.
The replay preserved every previously valid volatility estimate and recovered isolated-gap windows;
see docs/research/volatility-sampling.md. Require1800seconds of valid warm-up by default and
explicitly report effective spans/counts. Retain jumps. Stress the larger variance-rate estimate
by a multiplier 1.25 on sigma. For each side take the minimum probability across both estimates
and the stress, with an adverse USD10 reference shift. These are sensitivity scenarios, NOT
statistical confidence intervals. Every default is a hypothesis recorded with a configuration hash.

Evaluate both actual outcome books. For `value`, require the side-specific scenario floor minus
expected ask-depth cost, estimated buy fees across consumed levels, a worst-case sell-fee
reserve rate*(0.25**exponent) per share, and one-cent additional price allowance to exceed
0.02/share. Default acceptable ask band is 0.60..0.92; apply its maximum to the rounded signed buy limit,
not merely the best ask. Max selected-side spread is 0.03. Record each cost-reserve component.
The displayed model probability is not considered ground truth or proven better than the market.
For `momentum`, use abs(spot-reference)>=70, direction of that move, selected-side ask>=0.70,
ask<=0.95, and 90..150 seconds left. Same data, price/depth, sizing and execution protections apply.
Baseline timing/price/move settings remain explicit configuration rather than hardcoded secret logic.

All prices, cash, quantities, fees and receipts use Decimal. Float math is isolated to probability
and volatility calculations; reject NaN/Infinity. Book levels are validated and sorted explicitly.
Missing bids/asks, crossed books, future timestamps or stale data reject entries. Snapshots carry
both source and receive times; a healthy connection does not make an old quote fresh. Default
maximum price/book age is 5 seconds, future tolerance 1 second. Each decision records the reason.

## Position size and exit policy

Use fixed small exposure; one position and at most one opening intent per round. Default allocation
USD100, target all-in trade spending USD5, daily loss USD10, session loss USD10 and 20 entries/day.
Reserve maximum signed principal plus conservative fee allowance before posting, not just expected
VWAP. Exchange match-time fees can differ; spending is a configured target with a checked fee reserve,
not an impossible promise that an operator-set fee cannot change. Any actual breach halts new entries.
Use spend-based BUY semantics: buy_principal is the exact cash principal analyzed and signed;
expected_shares is the ask-depth estimate, minimum_receive_shares is the conservatively rounded
signed minimum at price_limit, and max_total_reserved includes principal and worst-case buy fee.
Consume the same principal across available asks, never convert expected shares using a higher
limit. Round principal down to supported precision; validate minimum shares after signed integer
rounding too. Better execution may deliver more shares; confirmed receipts determine inventory.
Daily (UTC midnight) and persisted session allowances each require:
max(0, -finalized_net_pnl) + remaining_position_cost_at_risk + unresolved_opening_reserves +
new_reservation <= loss_budget. Each exposure is counted once; confirmed opening cost replaces
its consumed reservation. Carry remaining inventory/reserves across midnight and restart.
Transfers, claims and external differences are not strategy profit. Thus USD9 losses plus a new USD5 reservation fails a USD10 budget.
Confirmed worthless residual inventory realizes its remaining basis loss even without a SELL receipt.
Never round up a position to satisfy minimum size if doing so exceeds the authorized reservation.
A USD100 dedicated wallet is the outer experimental allocation. No automatic reload or compounding.

Default exit triggers are an 0.08/share drop from actual entry price, selected bid at 0.98, or
20 seconds before expiry. These are experimental risk/profit/time choices, not optimized scientific
claims. Stop/take-profit triggers use depth-weighted executable gross price for the whole held quantity,
while reporting also subtracts expected sell fees. Actual entry price is confirmed BUY principal
divided by confirmed received shares, excluding
the buy fee. Inventory cost basis includes that fee and is allocated proportionally across partial
sales for realized net profit and risk accounting; do not use fee-inclusive basis as the price trigger.
If full depth is missing, do not fabricate a
full liquidation quote: time/shutdown triggers still permit a protected partial close against
available bids; remaining inventory stays unresolved. Evaluate sell-depth for actual held quantity; a last price or a best bid with insufficient
size is not a full liquidation quote. Triggering a stop requests a price-protected exit; it does not
guarantee the trigger price or prevent the full allocated loss. Sell attempt limit is a fresh
executable bid with bounded configured slippage; no stale-price or one-cent panic fallback.

Evaluate both candidates on the same available snapshots and retain each first eligible intent
per round, without invented fills/PnL. Record one calibration observation at the first snapshot
received 0..2 seconds after end-minus120; if absent, record missing rather than choose a later
favourable observation. Only the configured live candidate executes. This tests bundled strategies;
it does not isolate which individual filter caused a result.

No re-entry, opposite-side hedge, GTC fallback or general strategy plugin framework initially.
An exit attempt may partially execute. Reconcile the unsold remainder before another order.
If no safe exit is available, persist exposure, emit a prominent reason and continue monitoring.
Unexitable fractional holdings remain tracked through expiry. Require verified official resolution
before moving them out of active uncertain exposure. Verify binary payout mappings at one explicit
finalized Polygon block, retain/recheck its hash, and derive CTF singleton token IDs with underlying
USDC.e (distinct from trading-cash pUSD) to match saved tokens without relying on label order.
Require two slots and payouts exactly(1,0) or(0,1); zero denominator, fractional payouts, unknown
mapping/finality or outstanding order ambiguity remains unresolved. The verified public vector and
read-only ABI are in docs/research/sdk-contract.md. Resolved winning remnants remain owned claimable
inventory and are excluded from available cash; their existence alone does not permanently block the
next active round. Resolved losing remnants realize their remaining basis exactly once, while any
still-owned tokens stay in account reconciliation. Unknown-resolution remnants retain their risk.
Automatic redemption/approvals are outside this iteration. Report the manual Polymarket claim route and never count claimable shares as settled cash.

## Execution, recovery and accounting

One async process owns market streams, decision timing and a durable SQLite ledger. A wallet-scoped
live runtime under the common repository root plus an OS process lock prevents duplicate workers
across worktrees. Observe/test data use separate paths. SIGTERM and `stop` request graceful shutdown:
stop entries, manage existing orders/exposure, persist unresolved state. SIGKILL recovery is tested.

Only official polymarket-client==0.9.0 is used for venue integration. Authenticated read-only
commands must not use public AsyncSecureClient.create: it may deploy a missing deposit wallet.
Use one pinned adapter wrapper over _create with explicit existing wallet and all existing API
credentials, validate_credentials=False and api_key=None, then authenticated GET validation.
Require exact SDK version, known wallet relationship, chain137 and existing contract code for
non-EOA wallets. No credential creation/derivation fallback. Tests prohibit relayer/state-changing
HTTP actions on doctor/reconcile; JSON-RPC POST is restricted to read-only allowlisted methods.
Force fresh signing metadata through pinned order_metadata.fetch_current_market before creating
an order: the SDK otherwise caches fee/tick data for600 seconds. Compare fresh values to the
approved decision and reservation; invalidate/re-evaluate changes rather than silently spending more. Its place_* convenience methods
can issue unlimited approvals; they are forbidden. Use create_market_order with protected price,
BUY FOK and SELL FAK, persist signed payload/domain/hash in owner-only storage, then post_order once.
Never log replayable signed payloads. Credentials are read only for an explicit authenticated mode;
never on observe/help/public doctor. No shell sourcing of configuration or environment files.

The canonical CTF V2 EIP-712 hash is computed from the official domain/Order struct and verified
against a known vector/official contract hashOrder read-only call where reachable. Hash uses the
standard order domain/struct even when a wallet uses a nested signature wrapper. Commit intent and
hash before network POST. A timeout or ambiguous result becomes UNKNOWN, holds risk reserve and
blocks all new entries. No blind order retry or assumption that a single not-found means no fill.

Track orders and fills through provisional MATCHED/MINED/RETRYING and terminal CONFIRMED/FAILED.
Only fills with associated account trade status CONFIRMED AND a canonical successful receipt
finalize cash/inventory; receipt status=1 alone is insufficient. Finality is per fill, including
mixed FAILED/CONFIRMED orders. Acknowledged success is not settlement.
Account trade pagination and tracked open orders drive recovery, supplemented by onchain balances.
Cancellation targets owned recorded order IDs and is followed by fill reconciliation. A partially
confirmed order never releases its whole reserve. Per-round uniqueness survives restart.

A small read-only RPC adapter checks chain137 and fetches receipts/balances. Decode only verified
CTF V2 exchange OrderFilled events belonging to bot hashes, tokens and wallet. Receipt identity is
(chain,transaction hash,log index); repeated polling is idempotent. BUY cost=(makerAmountFilled+fee)/1e6,
SELL proceeds=(takerAmountFilled-fee)/1e6, quantities use the appropriate opposite field. Reject wrong
address/topic/status/owner/token or negative/invalid amounts for logs claiming the tracked order.
Ignore unrelated logs in batched receipts; they do not invalidate an otherwise valid owned fill. Preserve provisional
state if fee or receipt evidence is missing. Verify collateral decimals=6; CTF ERC1155 shares use the supported collateral-derived six-decimal
units and have no standard decimals() method. Never assume a deployed fee cap from source defaults.

SQLite records runs/config hashes, price observations, decisions, intents/signed orders, fill events,
positions, risk reservations, stop requests and account snapshots. Signed data storage is private;
public reporting selects safe columns. Observability records IDs, source/receive/decision/submit/fill
latencies, reason codes and sanitized error classes. Secrets, request auth and raw personal data are
never serialized. Reports distinguish estimated fees, actual fees, realized cash PnL, open inventory,
claimable value, external balance differences, funding and unresolved orders. Never reset daily loss
on process restart; session identity and limits also persist when resuming an interrupted run.

## CLI and repository surface

Provide `btc5m observe`, `doctor`, `run --execute`, `stop`, `status`, `report`, and `reconcile`.
No command defaults to live execution. Missing credentials/allowance identify required setup without
sending approval transactions. `doctor` is anonymous unless explicitly asked for account checks.
Configuration is one TOML file, validated with unknown-key rejection; safe CLI overrides are recorded.
No secret-valued command-line arguments. .env.example is documentation only; runtime accepts explicit
whitelisted env-file parsing or process environment, never shell evaluation. Runtime gets restrictive
permissions; logs cannot expose secrets in exception representations.

Replace/remove unsafe orphaned scripts and YAML rather than retain two strategy engines. Keep a thin
repo-local control wrapper if useful, with no implicit --execute. Rewrite README/SKILL/CONTOUR/examples
to describe real commands and limitations. This repair uses the verified native WSL/Linux route.
Remove the original Docker launcher/compose surface; Docker is unavailable in this WSL distro and
the old host-directory mount is unsafe. Do not add an unverified replacement container workflow.
Use CLAUDE.md -> AGENTS.md for shared context; .worktreeinclude must not copy .env/live data. Dependencies
and dev tools are pinned in pyproject/uv.lock. CI runs meaningful tests, lint, format and type checks.

## Completion evidence and limits

Required development evidence: core fee/model/decision tests; exact adapter fixtures and public
endpoint/stream smoke; hash/receipt independent vectors; risk/accounting/restart/concurrency/failure
scenarios; CLI defaults and graceful stop; an end-to-end synthetic account run using real core/ledger;
independent task and final reviews. No profitable backtest will be fabricated from synthetic checks.
Research outputs include sources, alternatives, evidence quality, current rule changes, and an
experiment protocol recording rejected rounds as well as fills. Calibration uses one outcome per
round, chronological splits and cluster-aware uncertainty; it is separate from stopped-policy PnL.

A funded end-to-end check remains a user stage: dedicated wallet, correct collateral/allowances,
explicit live command, observed hash/receipt/balance agreement. Until then call this development-
verified and live-unverified. Do not claim proven profitability or production trading readiness.
