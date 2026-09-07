# Why the first six-portfolio capture placed no orders

Read-only examination of the saved public and paper journals, 2026-09-07. Capture timestamps:
2026-09-06 23:10:37–23:48:42 UTC. Four runs, not one uninterrupted 38-minute observation.

## Decision checks for the value baseline

The other baseline/model/pair policies share several guards. These counts are repeated checks,
not independent trading opportunities. Only the first failed guard is recorded per check;
multiple problems can coexist.

| Reason | Checks | What the records establish |
| --- | ---: | --- |
| ENTRY_WINDOW | 1,392 | Evaluation occurred outside the configured entry interval. This is a scheduled wait. |
| INSUFFICIENT_HISTORY | 998 | 802 had a missing long-window start; 196 had an excessive long-window gap. |
| MISSING_BOOK_SIDE | 582 | A required bid or ask was absent; 202 checks were inside the entry window and 380 outside it. |
| MISSING_REFERENCE | 465 | 437 belonged to the initial round joined after its opening; the other 28 occurred briefly at later boundaries. |

The last history rejection had a full 1,800-second span, 352/361 samples (97.51% coverage),
but a **25-second gap between selected grid samples**. The configured maximum is 12 seconds.
The underlying source gap was 23 seconds, from 23:29:01 to 23:29:24, coinciding with the restart
recorded at 23:29:23. A second 22-second source gap coincided with the 23:47:56 restart.
Restoring recent observations preserved those real gaps correctly; it did not repair them.
Consequently, elapsed wall time above 30 minutes did not make the experiment ready.

The short/long sampling-status pairs across those 998 rejections were:
619 VALID/MISSING_START, 176 INSUFFICIENT_COVERAGE/MISSING_START,
4 MISSING_END/MISSING_START, 3 MISSING_START/MISSING_START, and 196 VALID/EXCESSIVE_GAP.

## Additional data failures

There were 181 metadata rejections: `/clob-markets` reported a tick size of 0.001 while
`/markets` reported 0.01. A tick is the smallest permitted price increment. The adapter rejected
this disagreement under its existing cross-check. These records alone do not establish which
endpoint was stale; choosing one requires further venue verification, not suppressing the error.

Of 19 stream-unavailable records, 10 were ordinary market switches, 6 were spot/TWAP disconnections,
2 were book-stream disconnections and 1 was an out-of-order book event. These are not 19 identical
outages. The snapshot collector also recorded 15 silent-feed events, 11 stale-data events,
2 warm-up events and 1 HTTP failure, in addition to the 181 metadata rejections.

Fast value separately rejected 55 stale exchange ticks, 94 alignment failures and one tick that
was not ahead of Chainlink. These guards prevent an assumed speed advantage from silently
replacing genuinely newer information.

## Interpretation and next experiment

All six ended with zero orders/fills and unchanged simulated cash. This provides no return or
execution-quality evidence. It does demonstrate that invalid inputs prevented entries, and
identifies operational constraints that need to be visible in the dashboard.

Keep the current thresholds for the initial continuous run. Let one collector acquire a clean
history window without development restarts, monitor sampling coverage/gaps and venue metadata,
and then inspect qualifying decisions and simulated fills. If clean uninterrupted data still
cannot produce usable windows, investigate the feed contract before changing the strategy.
