# BTC five-minute trading experiment

Standalone Polymarket BTC Up/Down bot. Read docs/design.md, docs/plans/standalone.md,
and docs/research/ before changing strategy or execution. Research defaults are hypotheses,
not validated returns. This repository is separate from Alpha-Sentry.

Project memory: .claude/memory/MEMORY.md. Log new project lessons there via /retro.

## Stack

Python 3.12, uv, pinned official polymarket-client 0.9.0, SQLite, Decimal.
The declared HTTP/Ethereum packages are already SDK dependencies; they are explicit because
our read-only receipt/hash adapter uses them. No language model in the trading loop.

## Commands

Use /home/vilius/.local/bin/uv if uv is absent from PATH.
Run git status --short before edits and git branch --show-current before commits.
Runtime/check commands are added once verified during implementation.

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

## Conventions

src/btc5m holds core, data, execution, ledger and CLI; tests mirror behaviours, not private code.
Write meaningful failing tests before high-impact implementation. Fixtures are synthetic or
public, timestamped and attributed. Financial claims distinguish estimates from receipt-confirmed cash.
Use small verified Conventional Commit checkpoints. Record task/review progress in docs/progress.md.
