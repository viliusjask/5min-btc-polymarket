# Design review rulings — 2026-09-06

Scientific review: all five findings accepted. Source-time model horizon, deterministic fee allowance,
remaining loss budgets, modified-baseline labeling/paired observations and bounded source-grid sampling
are incorporated into design and Task1 contracts.

Execution review: all six findings accepted. The pinned no-deploy/no-key-creation SDK factory,
forced signing-cache refresh and independent held-token book are explicit Task3 requirements.
Task1 now defines cash-principal BUY sizing and minimum/expected shares separately. Reference status,
cache provenance, required trading flags and monotonic connection clocks are explicit. UTC/session
risk counts outstanding exposure once. Finality requires CONFIRMED trade plus successful receipt;
unrelated batched logs are ignored. SDK private interfaces require exact version/signature guards.

Ruling: proceed to Task1 after these specification corrections. Funded validation is a later explicit
stage; neither paper infrastructure nor a claimed profitable backtest is a development gate.

Anchor ruling: two measured source boundaries now agree with both prior finalPrice and next
priceToBeat. The15:40 boundary distinguishes exact second from both neighbors. Permit exact
captured TWAP60 boundary anchors by default; missing ticks skip, later conflicts pause. Absolute
USD1e-8 comparison tolerance covers published JSON numeric precision. This enables the intended
live experiment without substituting a different price source. See docs/research/anchor-probe.md.

Residual ruling: SDK SELL rounding can leave fractional shares. Unknown-resolution residuals remain
active exposure; verified resolved winners become tracked claimable holdings, never cash, and losing
remaining basis is realized once. Resolved holdings remain known to reconciliation but do not block
all future rounds merely because manual claim has not occurred. No undocumented small-SELL exemption
or actual minimum-size acceptance is assumed. This prevents a one-trade permanent halt on normal dust.
