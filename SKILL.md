---
name: btc5m-operator
description: Observe, diagnose, explicitly run, stop, and inspect this standalone Polymarket BTC five-minute experiment through its native CLI.
---

Use this checkout's `uv run --locked btc5m`; read [README.md](README.md) for verified commands,
existing-account prerequisites, manual claims, and limitations. [CONTOUR.md](CONTOUR.md) identifies
the source/runtime boundaries. The canonical configuration is `config/btc5m.toml`; do not recover
old profiles or delegate execution to another trading repository.

Anonymous `observe` and public `doctor` need no credentials. An observation records both raw
candidate screens and eventual official references, never invented fills or paper profit. Allow
at least30 minutes of source-history warm-up; use a finite35-minute observation for initial evidence.

Funded execution requires the operator's explicit authorization and `run --execute --duration ...`.
Never add `--execute` to a wrapper or infer authorization from an eligible screen. Use existing
owner credentials only, passed through the process environment or an explicit private env-file.
Do not create/derive credentials, deploy wallets, approve, transfer, or redeem. CLOB L2, Relayer,
and Builder credentials are different. Account doctor is read-only and may run before a live
journal exists. Session/scoped signers are unsupported.

Use the absolute live journal path printed at startup for `stop`, `status`, and `report`.
Live paths are wallet-scoped under the common Git root across worktrees; never create a second
live runtime to bypass an owner lock, stop, loss budget, unknown order, or existing inventory.
`reconcile` reads the venue but writes local evidence, so it requires the same exclusive owner lock.
`run --execute` alone acknowledges an old stop once; new concurrent stops must survive.

A raw eligible screen, a pending confirmation, a submitted order, and a receipt-confirmed fill
are different states. Report actual fees/cash/PnL separately from estimated exit quotes, remaining
risk, unknown submissions, and claimable noncash inventory. Shutdown shares one deadline across
reconciliation, cancellation and transport cleanup, and can end unresolved. The bound assumes
prompt cancellation acknowledgement; execution must stop before the owner lock is released.
Follow README recovery instructions if blocked code prevents termination;
never call it flat without the ledger evidence. An uncertain order is not automatically replayed.
Use the same wallet's official manual claim route and preserve unresolved journal evidence.

This repair is development-verified and funded-live-unverified. Strategy defaults and confirmation
are experiments, not evidence of higher returns. Preserve rejected rounds and one calibration
sample/outcome per round as described in the design; do not turn repeated snapshots into successes.
