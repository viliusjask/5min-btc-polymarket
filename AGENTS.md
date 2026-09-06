# BTC five-minute trading experiment

Standalone Polymarket BTC Up/Down bot. Read docs/design.md, docs/plans/standalone.md,
docs/six-strategies.md and docs/research/ before changing strategy or execution. The six-strategy
extension supersedes older deferrals of strategies 3–6. Research defaults are hypotheses,
not validated returns. This repository is separate from Alpha-Sentry.

Project memory: .claude/memory/MEMORY.md. Log new project lessons there via /retro.

## Stack

Python 3.12, uv, pinned official polymarket-client 0.9.0, SQLite, Decimal.
The declared HTTP/Ethereum packages are already SDK dependencies; they are explicit because
our read-only receipt/hash adapter uses them. No language model in the trading loop.

## Commands

Use /home/vilius/.local/bin/uv if uv is absent from PATH.
Run git status --short before edits and git branch --show-current before commits.
Verified native Linux/WSL commands (Python 3.12, uv 0.11.24):

```bash
uv sync --locked
uv lock --check
uv run --locked pytest -q
uv run --locked ruff check src/btc5m tests
uv run --locked ruff format --check src/btc5m tests
uv run --locked mypy src/btc5m
uv run --locked btc5m --help
uv run --locked btc5m doctor --duration 15
uv run --locked btc5m observe --duration 2100 --runtime work/observe-35m/ledger.sqlite
uv run --locked btc5m report --runtime work/observe-35m/ledger.sqlite
uv run --locked btc5m paper --strategies all --duration 3600 --runtime work/paper-six
uv run --locked btc5m report --runtime work/paper-six
```

The 35-minute anonymous observe/report path completed on ac32575; final-source 3f49231 doctor/help
and retrospective report checks also passed. Full final suite 412 passed; independent rereview approved.
These are dated evidence, not a substitute for checks after changes. Funded operation remains
unverified. The six-strategy extension's current checks are in docs/progress.md. Read README.md
before explicit account/run/reconcile commands; no account setup occurs automatically.
`run --execute --duration ...` is the only trading mode. `scripts/btc5m_ctl.sh` forwards exact CLI
arguments, never execution consent. Status/report/stop use an explicit runtime path without secrets.
Live data is common-root `.runtime/<wallet>/ledger.sqlite`; anonymous data is separate. Run and
mutating local reconcile require the same exclusive owner lock. Readonly account doctor works with
or without an existing live journal. Never recover the removed legacy scripts/Docker/YAML workflow.

## Non-negotiables

- Preserve upstream history. Feature worktrees only; user handles merges. Never delete branches.
- Development uses anonymous feeds and synthetic account fixtures. No real orders, approvals,
  transfers or credential inspection without the corresponding user-authorized live step.
- Never call SDK place_* convenience methods: they can perform automatic unlimited approval.
  Public secure-client create may deploy a wallet; only the pinned no-deploy adapter may initialize auth.
  Sign, persist the exact intent/hash, then post once. Unknown submission freezes new entries.
- Never replace actual settlement rules with spot-price assumptions. Unknown rule/anchor means skip.
- Missing/stale data and accounting uncertainty are visible. No manufactured quotes, fills or PnL.
- Use Decimal for cash, prices, shares and receipt accounting. Floats are allowed for model math.
- No secrets or replayable signed payloads in ordinary logs. Credentials stay out of worktree copies.
- Share live ledger only via an explicit common-root, wallet-scoped runtime and process lock;
  development and observation data remain separate. Do not symlink secrets or venvs across workers.
- Runtime configuration has one validated source. No unimplemented advertised safeguards.
- Paper journals and live journals are distinct environments. Public-history restoration does
  not refresh source timestamps, restore exchange queue continuity, or certify profitability.
- Credential provisioning is only through the operator's explicit `credentials` command. Builder
  tuples, CLOB trading tuples and Relayer keys have different purposes. Gmail export addresses
  identify signers; the Polymarket profile supplies the account/funder wallet.

## Conventions

src/btc5m holds core, data, execution, ledger and CLI; tests mirror behaviours, not private code.
Write meaningful failing tests before high-impact implementation. Fixtures are synthetic or
public, timestamped and attributed. Financial claims distinguish estimates from receipt-confirmed cash.
Use small verified Conventional Commit checkpoints. Record task/review progress in docs/progress.md.

For the six-strategy implementation the user explicitly selected a single-agent workflow with
no cross-model reviews, conductor, management ceremony or human development checkpoints. Older
plan review gates are historical; own code review, relevant tests and feature-branch discipline apply.
