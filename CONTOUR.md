# Standalone execution boundary

The only strategy/execution path is `btc5m.cli` → `MarketData` / `Engine` → `Broker` / `Ledger`.
`python -m btc5m` and the installed `btc5m` command share that entry point.
`scripts/btc5m_ctl.sh` is a quoted native CLI delegate; arguments and explicit execution consent
are unchanged. There is no external runner, Docker mount, profile YAML, automatic watcher,
chat delivery, or duplicate report engine in the supported workflow.

| Responsibility | Source |
| --- | --- |
| Validated configuration and immutable data | `src/btc5m/config.py`, `domain.py`, `config/btc5m.toml` |
| Raw value/momentum screens | `src/btc5m/strategy.py` |
| Anonymous streams, discovery, books and official references | `src/btc5m/market_data.py` |
| Serialized confirmation, reconciliation and protected exits | `src/btc5m/engine.py` |
| Explicit existing-account reads, signing and one POST | `src/btc5m/broker.py` |
| Allowlisted Polygon reads and receipt/resolution verification | `src/btc5m/rpc.py` |
| Typed evidence and durable accounting/control | `src/btc5m/execution_types.py`, `ledger.py` |
| Native lifecycle and safe public reports | `src/btc5m/cli.py`, `__main__.py` |

The CLI polls complete snapshots independently of account I/O and records paired screens and
calibration immediately. Its immutable latest input and monotonic invalidation generation preserve
intervening gaps/rejections/identity excursions. The Engine samples after reconciliation and after
BUY preparation. Held books are fetched for the actual reconciled token, after account I/O and
independently of discovery, including during shutdown. Real time is refreshed after awaited reads.

Live journal: `<common-git-root>/.runtime/<lowercase-wallet>/ledger.sqlite`, shared across source
worktrees through the canonical path helper, with an exclusive process owner for run/reconcile.
Readonly report/status/account doctor and the dedicated stop write can operate alongside that owner.
Anonymous default: `<common-git-root>/.observations/<unique-id>/ledger.sqlite`; explicit observation
paths must remain outside the live namespace. Credentials, virtual environments and journals are
not copied between worktrees. Existing credentials are loaded only by explicit authenticated modes.

[README.md](README.md) is the operator guide; [docs/design.md](docs/design.md) is the behavioral
contract. The implementation is development-verified and funded-live-unverified. Preserve all
branches/worktrees and upstream history; the user handles publication and merging decisions.
