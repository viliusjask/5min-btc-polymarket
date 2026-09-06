# Standalone BTC five-minute experiment

This repaired version observes Polymarket BTC Up/Down markets, screens two explicit strategies,
and can submit small protected orders only through `run --execute`. It runs independently of
OpenClaw, Alpha-Sentry, and other trading repositories. SQLite preserves actual orders, receipts,
fees, inventory, risk budgets, and uncertain submissions across restarts.

**Development-verified; funded trading remains unverified.** Tests exercise the real strategy,
pinned SDK signing, receipt adapter, and SQLite using synthetic venue responses. Anonymous public
feeds and read-only endpoint probes were exercised. No funded order, account setup, approval,
transfer, credential creation, or claim was performed during this repair. Neither the research
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
| Value ask band / maximum spread | 0.60–0.92 / 0.03 |
| Value minimum terminal surplus proxy | 0.02/share after estimated fees and allowances |
| Momentum comparison | USD70 move, ask0.70–0.95, 90–150 seconds left |
| Raw volatility windows / stress | 300 and1800 seconds / 1.25 times sigma |
| Adverse reference scenario | USD10 |
| Price/book maximum age | 5 seconds; future tolerance1 second |
| Experimental allocation / trade spending target | USD100 / USD5 |
| Daily and session loss allowance | USD10 each, including remaining exposure/reserves |
| Maximum entries per UTC day | 20, persisted through restart |
| Exit requests | 0.08/share below gross entry, bid0.98, or20 seconds before expiry |
| BUY / SELL price allowance | 0.01 / 0.01 |

Defaults are research hypotheses. A terminal surplus proxy compares modeled final value with
entry costs; it is not expected profit under the early-exit policy. The full rationale, including
scientific papers and human trading evidence, is in [strategy decisions](docs/research/strategy-decisions.md).
The complete source registers are [scientific research](docs/research/scientific-strategy.md),
[trader evidence](docs/research/trader-sentiment.md), and the [SDK contract dossier](docs/research/sdk-contract.md).
[Design](docs/design.md) specifies the operating contract and
[public integration evidence](docs/research/adapter-integration-probe.md) records availability limits.

Both candidates are recorded on the same snapshots. Only the configured candidate can execute.
An eligible raw screen first arms an unreserved pending candidate. A subsequent fresh underlying
point must be newer than the original point and reach the original candidate book timestamp;
the current screen must still qualify. Missing data, an intervening rejection, an identity
change, stop, or account uncertainty cancels it. Restart drops pending candidates. This
[experimental confirmation rule](docs/research/information-alignment-review.md) does not guarantee
current feed alignment or improved returns.

Observation records preserve the first eligible raw screen for each candidate/round, and the
first snapshot received0–2 seconds after end-minus120 seconds for calibration. An absent sample
is marked missing after that interval. Official eventual final references are recorded per round;
repeated snapshots do not become independent winning trades. No fill rates or paper PnL are invented.

## Existing account setup and one small funded experiment

The following is an **operator stage**, not development verification. Use a dedicated account
with no external concurrent trading, already provisioned with the intended USD100 experimental
allocation, Polygon137 trading cash **pUSD**, the correct collateral allowance, and conditional-token
selling approval. Allowances and the wallet's available collateral must already exist; this bot
will report deficiencies and will not repair them. Follow the official
[account/authentication instructions](https://docs.polymarket.com/trading/wallets-auth) and
[trading setup](https://docs.polymarket.com/trading/quickstart) manually before using these commands.

The five inputs are an existing owner private key, explicit account/funder address, and existing
**CLOB L2** key, secret, and passphrase. CLOB credentials are distinct from Relayer and Builder
credentials. The website Settings → API Keys → Relayer API Keys route is not a CLOB tuple export;
the official account page documents CLOB provisioning separately. This application never creates
or derives credentials, deploys a deposit wallet, sets allowances, transfers funds, or redeems
positions. Scoped/session signers are unsupported. These distinctions and the pinned SDK's
no-deployment construction path are documented in the [dossier](docs/research/sdk-contract.md).

Store already provisioned values in a private file outside the checkout with mode0600, or supply
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
window is bounded; exit2 means failure or unfinished work requiring inspection, not liquidation.
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
