# Reusable public market archive and historical replay

The user explicitly requested persistent asset history to test future strategies rapidly,
and authorized implementation after verifying the historical-data premise. Extend the
existing collector and replay engine; do not start a duplicate collector or reset any study.
The unified monitoring work is already deployed and published as PR14; keep its checkout stable.

## Design and ownership

- Independent archive worker (`feat/archive-capture`) owns accepted independent oracle
  ticks, pre-consolidation public book messages, narrow public rule/fee/tick metadata and
  capture-session source/config identity. Additive archive data must survive invalid trading
  snapshots while preserving all prior snapshot/research semantics and pinned readers.
  Bound record size and pending buffers; explicit dropped-sequence markers distinguish
  overload and uncommitted tails from complete history. No fabricated E18 wire field when
  the pinned SDK exposes only exact Decimal values.
- Independent ledger worker (`fix/ledger-history-read`) owns the confirmed per-step scans
  of settled intent history and historical daily entry counts. Preserve ordering, states,
  transactional behavior and read-only legacy opens; regression tests must verify bounded
  SQLite work even before planner statistics exist.
- Historical replay owns a finite, explicit entry time range and selected variants in a
  new study directory. Reuse Study, Tape and Replay; preserve causal warmup, continue later
  archived frames for exits/labels, and label the result exploratory. Existing registered
  study defaults and pinned workers remain unchanged. Include bounded coverage/status
  information and an explicit safe backup procedure, without automated deletion.
- Root owns the cited availability research, integration plan, overall review, actual
  archive/replay verification, preserving runtime cutover and PR publication. After the
  independent work returns, obtain a separate combined review/integration pass.

No new runtime dependency, secrets, funded action, new venue subscription, historical flag
rewriting, automatic backfill or destructive retention. Record only the public inputs
already subscribed to by this BTC application. Additional historical sources can later be
evaluated for provenance and coverage; availability is not evidence of perfect completeness.

## Acceptance

Archive regression tests must cover rejected snapshots, causal receipt order, reconnects,
oversized/overflow input, restart durability and old-reader compatibility. Historical
replay must reject invalid ranges/IDs without changing existing studies; verify no entries
outside the interval, later exits/labels, bounded source selection and preserved uncertainty.
Run the existing static gates and one combined full test suite after integration. Exercise
a small real public capture plus a selected historical replay, keeping source archive and
ongoing studies read-only except the explicitly deployed collector. Preserve seven account
sessions, financial prefixes, both pinned worker identities and study manifests on cutover.

## Starting evidence

At about 08:36 UTC September 8, the existing source archives held approximately 4.27 GiB:
0.967 GiB/98,911 tape frames over 25.16 hours and 3.303 GiB/2,377,151 observations over 31.97 hours.
These mixed-policy/outage lifetime rates are not future healthy-run capacity forecasts.
No automatic pruning exists. Ordinary exchange price history is available externally;
the exact TWAP live endpoint has no reconnect replay. See the accompanying research note.
