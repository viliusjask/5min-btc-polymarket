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
