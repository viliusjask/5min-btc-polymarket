# Standalone BTC five-minute experiment

This repaired version observes Polymarket BTC Up/Down markets, implements six explicit strategies,
compares independent simulated portfolios, and submits funded orders only through `run --execute`. It runs independently of
OpenClaw, Alpha-Sentry, and other trading repositories. SQLite preserves actual orders, receipts,
fees, inventory, risk budgets, and uncertain submissions across restarts.

**Development-verified; funded trading remains unverified.** Tests exercise the real strategy,
pinned SDK signing, receipt adapter, and SQLite using synthetic venue responses. Anonymous public
feeds and read-only account checks were exercised. No funded order, approval,
transfer, or claim was performed during development. Credential provisioning is an explicit
operator command. Neither the research
nor the checks establish profitability or production trading readiness.

## Native setup and anonymous checks

Use Linux or WSL with Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From this repaired checkout:

```bash
uv sync --locked
uv run --locked btc5m --help
uv run --locked btc5m doctor --duration 15
uv run --locked btc5m observe --duration 2100 --runtime work/observe-35m/ledger.sqlite
uv run --locked btc5m report --runtime work/observe-35m/ledger.sqlite
```

`observe` collects for 35 minutes, allowing the default 30-minute source-history warm-up plus
several rounds. Warm-up can take longer after gaps. It records missing references, stale inputs,
rejected screens, and absent calibration samples; a completed observation is not a simulated
trade or a profit estimate. Public `doctor` checks that spot, TWAP60, and market discovery were
observed during its finite window. Its success does not certify a trading-ready snapshot or
account. These commands never read credentials or construct an authenticated client.

The verified operating path is native Linux/WSL. The original Docker launcher, compose mount,
YAML profiles, and duplicate strategy/report scripts were removed. No container workflow is
advertised. `scripts/btc5m_ctl.sh` delegates the same arguments to this CLI, with quoted paths;
it never supplies `--execute` for you. The package uses its checkout's `config/btc5m.toml`,
independent of the shell's current directory. `--config` explicitly selects another complete TOML
file; unknown or missing keys fail validation. This setup uses an editable checkout, not a
standalone wheel with bundled configuration.

## Run the six simulated portfolios

No API credentials or wallet are used by this command:

```bash
uv run --locked btc5m paper --strategies all --duration 3600 --runtime work/paper-six
uv run --locked btc5m report --runtime work/paper-six
uv run --locked btc5m stop --runtime work/paper-six
```

The configured USD100 total is split into six independent USD16.66 simulated portfolios,
leaving USD0.04 unused. Each has its own orders, positions, fees, cash and risk checks.
`--strategies value,model_exit` compares a subset, splitting the same total between them.
The first run needs about 30 minutes of Chainlink history. Restarting the **same** paper runtime
restores recent recorded price history but still requires fresh feeds; a real gap stays a gap.
The same directory resumes balances and daily limits. Changed configuration requires a new directory.

For **USD100 per strategy**, copy `config/btc5m.toml` to a local file under `work/`, change only
`risk.allocation_usd` to `600`, and pass it with `--config`. That is USD600 simulated total;
the per-entry budget and loss limits remain separate settings. Use a fresh runtime directory.

For continuous operation, use `paper --continuous` instead of `--duration`. The installed
WSL services preserve the existing six USD100 portfolios outside the worktrees and run
independently from Codex. See [service controls, Windows startup and recovery limits](docs/paper-service.md).

## Paper and real account dashboard

In another terminal, point the dashboard at the paper run's directory:

```bash
uv run --locked btc5m dashboard --runtime work/paper-six --port 8765
```

Open [the local dashboard](http://127.0.0.1:8765/). It refreshes every five seconds and includes
six portfolio cards, recorded profit/loss, orders and fills, Bitcoin prices, feed health, history
sampling and explanations for skipped entries. Use the same `--config` as the collector to show
its thresholds. The collector and dashboard are separate processes: closing or restarting the
page/server does not interrupt paper trading. The dashboard starts no collector of its own.

**Paper / Real at the top switches views only.** Paper needs no credentials. To also connect the
Real view, explicitly provide the existing ignored account file:

```bash
uv run --locked btc5m dashboard --runtime work/paper-six --port 8765 \
  --account --env-file /absolute/path/to/.env
```

Account reads start when the Real view is requested and refresh at most once every 30 seconds.
It shows Polygon trading cash, indexed holdings and estimated values, actual open orders,
the latest page of account trades within seven days, and local funded-bot accounting when a
live journal exists. Maker trade rows use this wallet's matched leg, excluding other participants'
size and API-key owner fields. Account activity from outside this bot is labelled separately.
Position estimates can lag; balances plus holdings are not a profit calculation. Trade statuses
are venue reports, while the bot's live ledger only records fills after receipt verification.
Unavailable sections display unknown values. Monitoring does not provision credentials, create
a live journal, initialize funds, approve, place/cancel orders, or redeem positions.

The server binds to `127.0.0.1`, offers read-only routes, and has no browser credential form.
JSON export contains the selected view's safe snapshot, which can include your account address
and trading activity. Never share a real-account export unintentionally. No runtime dependencies
were added for the dashboard.

Zero fills means **awaiting first trade**, not demonstrated flat performance. Public trade records
are other market participants' activity. The original 38-minute capture had no bot orders or
fills; [its missing-data diagnosis](docs/research/paper-capture-diagnosis.md) explains the restart
gaps that continued blocking entries after warm-up. New collectors record a heartbeat and final
stop state; older captures are labelled historical. Decision counts are repeated checks, not
independent opportunities. Charts retain the latest 24 hours of public observations, while
counters and accounting remain cumulative. Account-wide lifetime returns are not inferred.

## The six policies

| # | CLI strategy | What changes |
| --- | --- | --- |
| 1 | `momentum` | Late directional baseline using the BTC move, entry band and hard exits. |
| 2 | `value` | Settlement-aware probability, executable depth, fees and conservative sensitivity scenarios. |
| 3 | `fast_value` | Strategy 2 with a Binance BTCUSDT return aligned to the latest Chainlink point. |
| 4 | `model_exit` | Strategy 2 entries, plus a fresh sale-versus-hold decision, including the final averaging minute. |
| 5 | `passive_pairs` | Sequential post-only Up/Down quotes with a capped completed-pair cost and unmatched-inventory timeout. |
| 6 | `inventory_pairs` | Strategy 5 with more aggressive hedge quotes as inventory imbalance and binary uncertainty increase. |

All six have executable code and use the same execution coordinator. Paper substitutes a
simulated broker; funded `run --strategy NAME --execute` uses Polymarket's official SDK.
`run --strategy compare --execute` preassigns one policy per UTC round using round index modulo six,
with **one shared actual wallet, ledger and total budget**. It is not six independently funded accounts.
Open inventory can block subsequent assigned rounds. External account trading remains unsupported.

Paper orders wait at least 250ms and require a subsequent fresh book. Immediate buys consume the
requested cash amount through available asks; protected sells can fill partially. Resting quotes
require subsequent matching sell volume or complementary opposite-outcome buying to consume
observed same-price queue depth before simulated fills.
A touched bid is never itself a fill. Queue position is approximate; stream gaps/restarts make an
active queue uncertain. The report identifies those rounds. Portfolios do not compete with each
other for depth, and simulated settlement assumes free automatic redemption after official labels.
No maker rebates are credited. These are measured simulation outcomes, not venue fills or verified ROI.
See [six-strategy mechanics and limits](docs/six-strategies.md).

The corrected passive model also matches buying of the **opposite outcome** at the complementary
price. Transaction identity prevents mirrored reports from counting the same flow twice. Earlier
paper orders omitted this path and remain flagged as historical results of the old model; their
cash and trades are not rewritten. [Recorded zero-fill diagnosis and replay](docs/research/paper-fill-diagnosis.md).

## What is being tested

Only the verified ordinary BTC five-minute settlement rule is supported: the ending Chainlink
60-second time-weighted average (TWAP60) compared with the opening reference; Up includes equality.
The opening reference must be official or an exact source-timestamp boundary observation under
the verified capture policy. Missing/conflicting anchors or unsupported rules prevent entries.
Both outcome books and raw Chainlink spot history are required; there is no substitute price feed.

| Setting | Default |
| --- | --- |
| Selected executable screen | `value` |
| Shared new-entry window | 60–180 seconds before expiry |
| Value ask band / maximum spread | Positive executable prices up to0.92; no lower floor / 0.03 |
| Value minimum terminal surplus proxy | 0.02/share after estimated fees and allowances |
| Momentum comparison | USD50 move, ask0.70–0.95, 90–150 seconds left |
| Raw volatility windows / stress | 300 and1800 seconds / 1.25 times sigma |
| Adverse reference scenario | USD10 |
| Price/book maximum age | 5 seconds; future tolerance1 second |
| Experimental allocation / trade spending target | USD100 / USD5 |
| Daily and session loss allowance | USD10 each, including remaining exposure/reserves |
| Maximum entries per UTC day | Disabled (0); explicit positive limits persist through restart |
| Exit requests | 0.08/share below gross entry, bid0.98, or20 seconds before expiry |
| BUY / SELL price allowance | 0.01 / 0.01 |

Defaults are research hypotheses. A terminal surplus proxy compares modeled final value with
entry costs; it is not expected profit under the early-exit policy. The full rationale, including
scientific papers and human trading evidence, is in [strategy decisions](docs/research/strategy-decisions.md).
The complete source registers are [scientific research](docs/research/scientific-strategy.md),
[trader evidence](docs/research/trader-sentiment.md), and the [SDK contract dossier](docs/research/sdk-contract.md).
[Design](docs/design.md) specifies the operating contract and
[public integration evidence](docs/research/adapter-integration-probe.md) records availability limits.

The [entry-filter comparison](docs/research/entry-filters-and-dashboard.md) records why the
60-cent Value floor was removed and Momentum's lead reduced fromUSD70 toUSD50 for paper testing.
More candidate checks do not establish better returns. Below8-cent entry prices, the unchanged
absolute8-cent stop cannot trigger before the token reaches zero; time/model exits and the
USD5 spending cap still apply. A stop request never guarantees a sale.

`observe` defaults to recording the two original baselines. `observe --strategy compare` and
`paper --strategies all` record all six on the same public snapshots. Only the selected policy can
execute in an individual funded round.
An eligible raw screen first arms an unreserved pending candidate. A subsequent fresh underlying
point must be newer than the original point and reach the original candidate book timestamp;
the current screen must still qualify. Missing data, an intervening rejection, an identity
change, stop, or account uncertainty cancels it. Restart drops pending candidates. This
[experimental confirmation rule](docs/research/information-alignment-review.md) does not guarantee
current feed alignment or improved returns.

Observation records preserve the first eligible raw screen for each candidate/round, and the
first snapshot received 0–2 seconds after end-minus120 seconds for calibration. An absent sample
is marked missing after that interval. Official eventual final references are recorded per round;
repeated snapshots do not become independent winning trades. `observe` produces no simulated fills;
only the explicit `paper` broker produces labelled simulated execution and PnL.

## Existing account setup and one small funded experiment

The following is an **operator stage**, not development verification. Use a dedicated account
with no external concurrent trading, already provisioned with the intended USD100 experimental
allocation, Polygon137 trading cash **pUSD**, the correct collateral allowance, and conditional-token
selling approval. Allowances and the wallet's available collateral must already exist; this bot
will report deficiencies and will not repair them. Follow the official
[account/authentication instructions](https://docs.polymarket.com/trading/wallets-auth) and
[trading setup](https://docs.polymarket.com/trading/quickstart) manually before using these commands.

The five inputs are an existing owner private key, explicit account/funder address, and
**CLOB L2** key, secret, and passphrase. CLOB credentials are distinct from Relayer and Builder
credentials. The website Settings → API Keys → Relayer API Keys route is not a CLOB tuple export;
the official account page documents CLOB provisioning separately. The explicit `credentials`
command creates or derives the trading tuple. Trading/account commands never provision keys,
deploy a deposit wallet, set allowances, transfer funds, or redeem
positions. Scoped/session signers are unsupported. These distinctions and the pinned SDK's
no-deployment construction path are documented in the [dossier](docs/research/sdk-contract.md).

Store values in a private file with mode0600, or supply
the same names through the process environment. Never put actual secrets into shell arguments,
Git, or a shared task. An explicit file accepts only these keys, one `KEY=value` per line;
optional matching quotes are literal, and neither shell expansion nor `source`/`eval` is used:

```text
POLYMARKET_PRIVATE_KEY=<existing owner private key>
POLYMARKET_FUNDER=<public account wallet address>
POLYMARKET_API_KEY=<existing CLOB L2 key>
POLYMARKET_API_SECRET=<existing CLOB L2 secret>
POLYMARKET_API_PASSPHRASE=<existing CLOB L2 passphrase>
```

For Gmail/email accounts, follow Polymarket's [official key-export guide](https://help.polymarket.com/en/articles/13364258-how-do-i-export-my-key).
The exported private key signs authentication and orders. The account wallet copied from the
**Polymarket profile menu** supplies `POLYMARKET_FUNDER`; the address on the export page identifies
the signer and can be different. Gmail does not by itself determine legacy Proxy versus newer
Deposit Wallet type; the adapter checks the signer/wallet relationship.

After setting the private key and funder, generate the three trading API fields locally:

```bash
uv run --locked btc5m credentials --env-file /absolute/path/to/.env --create
uv run --locked btc5m doctor --account --env-file /absolute/path/to/.env
```

The first command signs the official CLOB authentication message, obtains the tuple, and atomically
replaces only the three API fields in the explicit file, preserving comments and the other values.
It never prints credentials or sends an order. Omit `--create` to derive an existing tuple only;
after an uncertain creation response, use that derive-only form before attempting another creation.
Builder credentials do not belong in these fields. Relayer credentials authorize gasless wallet
operations such as approvals, merging and redemption; the current order path does not use them.
An ignored `.env` in the canonical checkout is supported through an explicit absolute path; it is
not copied or symlinked into worktrees. Git ignore rules prevent accidental tracking, not file reads.

Prepare a complete experiment config by copying `config/btc5m.toml` to `work/experiment.toml`
and changing only `risk.max_entries_per_day` to1. Keep the USD5 trade spending target and the
loss allowances. A daily cap of1 means at most one entry that UTC day, not one additional entry
on every restart. The run must include the 30-minute history warm-up; it may still make no entry.

```bash
uv run --locked btc5m doctor --account --env-file /absolute/private/btc5m.env
uv run --locked btc5m run --execute --duration 2400 --shutdown-seconds 60 --config work/experiment.toml --env-file /absolute/private/btc5m.env
```

`doctor --account` performs authenticated reads without adopting an initial cash balance or
creating a live session. With no live ledger, it uses isolated temporary local state. It can
also diagnose an existing account alongside its running owner. Account identity, allowances,
indexed holdings, actual balances, and limitations are reported explicitly.

Before increasing the experiment, inspect the actual order hash, account trade status, canonical
receipt, fee, and cash/token balance agreement. Record rejected rounds as well as submitted
orders. Keep parameter changes and configuration hashes visible; evaluate one outcome per round
chronologically. A profitable individual trade would not validate the strategy.

## Stop, inspect, and recover

Every live operation resolves the **common Git root**, even when started from a worktree:
`.runtime/<lowercase-account-wallet>/ledger.sqlite`. The run prints its absolute path. Anonymous
runs default to `.observations/<unique-id>/ledger.sqlite` under that common root, or accept an
explicit separate `--runtime`. Never copy or delete the live journal to reset a budget. Worktrees
keep independent source/virtual environments while sharing only the canonical wallet runtime.
Runtime leaf directories are mode0700; journal, lock and active SQLite sidecar files are mode0600.

Use the printed path in another terminal; no credentials are needed for these commands:

```bash
uv run --locked btc5m stop --runtime /absolute/common-root/.runtime/0xYOUR_WALLET/ledger.sqlite
uv run --locked btc5m status --runtime /absolute/common-root/.runtime/0xYOUR_WALLET/ledger.sqlite
uv run --locked btc5m report --runtime /absolute/common-root/.runtime/0xYOUR_WALLET/ledger.sqlite
uv run --locked btc5m report --records --runtime /absolute/common-root/.runtime/0xYOUR_WALLET/ledger.sqlite > work/safe-report.json
```

For a deliberately noncanonical existing journal path, supply its public `--wallet` as well.
Reports select safe Ledger APIs and omit signed payloads and authentication data. `status` shows
actual cash, receipt-confirmed fees and realized net PnL, reserved cash, remaining cost at risk,
owning quantities, claimable noncash value, unresolved orders, and stop/halts separately. `report`
adds paired-screen counts, confirmation events, calibration, final references and recent diagnostics;
`--records` includes the full public observation and decision history. A quote's estimated fee
is not an actual charged fee, and an accepted order is not a confirmed fill.

SIGINT, SIGTERM, `stop`, or the duration limit requests a protected unwind. The additional shutdown
window (`--shutdown-seconds`) is one shared deadline for reconciliation, protected closes,
task cancellation and transport cleanup, including when the account becomes flat early.
At that deadline, pending asynchronous work is cancelled; the process drains cancellation,
records its final summary and releases the wallet lock after execution has stopped. Cleanup
uses the remaining budget, so a slow close can consume that budget and produce exit2 even
when flat. Exit2 means failure or unfinished work requiring inspection, not liquidation.
Cancellation during a submitted order preserves UNKNOWN state and its reservation.

This bound assumes asynchronous operations promptly acknowledge cancellation. It allows event-loop
scheduling and final local journal/report work; it is not a hard real-time guarantee. Code that
suppresses cancellation, blocks the event loop, or stalls synchronous storage/output can delay
termination. Ownership stays held until execution stops; a second worker must not bypass that lock.
If shutdown remains stuck, terminate the existing process externally, confirm it has exited, then
inspect `status`/`report` and run the explicit `reconcile` command below before considering a restart.
An interrupted cleanup may leave transport resources for the operating system to reclaim on exit.

If no fresh executable bid is available, partial depth/minimum size prevents closing, resolution
is unverified, or a submission remains uncertain, inventory and reservations remain durable.
The original close request persists across partial fills and restarts; subsequent prices can differ.
A trigger price is not guaranteed. Confirmed winning remnants remain owned claimable inventory,
separate from cash; confirmed worthless remnants realize their remaining cost once.

`stop` remains set after termination. An explicitly restarted `run --execute` clears only the
old stop, once under the owner lock before account setup. A newer stop during setup/signing survives.
An uncertain submitted order is reconciled and is never blindly replayed. Status/report remain
available after abrupt termination. Venue-read-only reconciliation updates the local journal
under the same exclusive owner lock and refuses to run alongside an active trader:

```bash
uv run --locked btc5m reconcile --env-file /absolute/private/btc5m.env
```

Reconciliation applies order/account evidence without clearing stop or resetting budgets; the
held-position exit/resolution lifecycle remains in the running Engine. The indexed inventory API cannot prove
exhaustive onchain absence; external transfers/claims remain discrepancies rather than strategy
profit. Fees can change at match time; the configured spending target and reserve are not a
protocol-enforced all-in cap. Any actual breach halts entries.

For a website-managed account, claim resolved winning positions through that same account's
Polymarket portfolio. For a standalone externally owned account, use the official transaction
route for that wallet; its holdings need not appear in another website wallet. Follow
[official position management](https://docs.polymarket.com/trading/positions/manage).
This version performs no redemption and does not automatically account for manual claim receipts.
Preserve its ledger and investigate any balance discrepancy before continuing.

## Development verification

```bash
uv lock --check
uv run --locked pytest -q
uv run --locked ruff check src/btc5m tests
uv run --locked ruff format --check src/btc5m tests
uv run --locked mypy src/btc5m
```

These checks run in CI with Python3.12 and the lockfile. The SDK is pinned to0.9.0; unknown
versions fail closed. Full synthetic and public evidence, independent reviews, outstanding limits,
and experiment decisions are tracked in [progress](docs/progress.md) and [research](docs/research/strategy-decisions.md).
The journal has no automatic retention/migration service; keep this a bounded experiment.
