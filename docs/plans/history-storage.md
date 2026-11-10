# Compact storage and external historical replay

## Scope and accepted design

The September 8 request authorizes reducing persistent storage, appropriate rotation,
external historical backtesting, and independent work on promising strategy evidence.
Funded trading remains off. Existing accounts, experiment identities, financial history,
source timestamps and uncertainty flags must survive. The user handles PR merges.

Use the existing Python 3.12, SQLite, Decimal and paper execution/replay implementation.
No vendor SDK is needed to read the first source's gzip JSON/CSV files. No additional
runtime dependency or paid data is assumed. Historical imports are separate sources,
never retroactive edits to what the live collector observed.

Storage rotation means moving old required history into compact, readable storage.
It does not mean deleting the only copy of recorded market data. Bound disposable
operational logs independently. Any migration must verify its output before switching
readers or removing the redundant original, with interruption/restart tests and a
retained rollback path. The pinned studies' readers and identities are compatibility
requirements; their histories cannot be restarted to simplify a format change.

## Work and ownership

- [ ] Storage worker: trace every observations reader; implement compressed history and
  bounded recent storage, migration/status interfaces, integrity checks and rotation
  tests in `ledger.py`, a dedicated storage module, and `docs/storage.md`.
- [ ] Historical worker: implement a streaming, attributed OutcomeTick importer into the
  existing replay tape; validate identity, precision, timing and missing input coverage;
  exercise multi-round strategy evaluation with synthetic fixtures. Own importer modules,
  their tests and `docs/external-history.md`.
- [ ] Evidence worker: freeze an updated audit and separate results after the previous
  07:17 UTC report from its selected examples. Compare the preselected opening-reference
  Momentum candidate, its normalized comparator and the current Momentum policy. Own the
  follow-up research report; do not modify production strategy thresholds to force trades.
- [ ] Root: integrate CLI and service controls, acquire public data with bounded downloads,
  run historical comparisons, review worker changes and measure actual storage savings.
- [ ] Separate integration agent: review interactions and failure paths after the root's
  review; resolve introduced issues and verify compatibility on the combined source.
- [ ] Root: perform a verified service cutover and storage migration, preserving accounts
  and pinned studies; publish a feature PR and update commands/reference documentation.

## Acceptance evidence

1. Existing replay/account results and stable source/event IDs survive compression and
   migration. Corrupt/missing archives fail visibly. Interruptions cannot delete the last
   good copy. No current reader silently omits historical rows.
2. Actual data demonstrates reduced bytes and bounded recent storage. Compressed historical
   growth is reported honestly; indefinite unique tick history cannot have a finite size.
3. Imported data runs through the current strategy and execution code. No invented BTC
   settlement prices, fills, pre-start warmup or uninterrupted sampled book updates.
4. Reports distinguish no opportunity, missing prerequisites and unfilled orders, and show
   all results alongside data-quality-qualified results without rewriting the old flags.
5. Evaluate a fixed shortlist over external dates, keeping tuning and test periods separate.
   A source sample or a short positive subtotal does not establish profitability.
6. Appropriate regression tests and independent combined review pass before migration.

## Historical-source findings carried forward

The free OutcomeTick September 4 release contains current-rule BTC books/trades, spot,
TWAP60 and market outcomes. A bounded inspection reproduced 258 outcomes; 30 rounds lacked
an exact boundary report. Six sampled identities/outcomes matched Gamma. The linked main
manifest was stale (August 25), so local file hashes must be recorded independently.
Books are sampled and price changes are throttled; those are explicit execution limits.
PMXT is another free book source; PMData and longer OutcomeTick history require separate
coverage/access validation. No paid access is authorized by this implementation request.
