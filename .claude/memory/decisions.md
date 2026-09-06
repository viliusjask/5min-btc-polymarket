# Decisions

- 2026-09-06: User authorized autonomous research, design and implementation of a standalone
  repair with feature worktrees, subagents and review. Small funded experiment is the intended
  next stage; no funded execution or wallet setup was requested for this development run.
- 2026-09-06: Public scientific and trader evidence does not establish profitability for the
  original rule. Preserve baseline comparison and distinguish terminal-value proxy from actual
  stopped-policy profit. Do not make simulator construction a prerequisite for a bounded live trial.
- 2026-09-06: Current contracts identify Chainlink TWAP60; verify observed boundary anchoring
  against official metadata before treating captured boundary values as reliable live references.
- 2026-09-06: Two anonymous boundary comparisons passed, including a boundary distinct from
  neighboring seconds. Captured exact-boundary anchors are enabled; cached null metadata cannot
  erase them. Evidence and the current rule remain in docs/research/anchor-probe.md.
- 2026-09-06: Actual source gaps made a complete five-second grid unusable for long windows.
  A reviewed policy permits isolated missing samples with at least95% coverage and at most12s
  between accepted points; full-span/endpoints and current-price freshness remain required.
  In the completed32-minute raw-feed replay,24/24 long windows passed versus0/24 strict windows.
  This establishes operating availability, not more accurate probabilities or higher returns.
- 2026-09-06: Public positions discovery must request sizeThreshold=0 and includeArchived=true.
  Pinned SDK0.9 lacks the archive argument, so a narrow anonymous HTTP adapter is intentional.
  The index supplies candidate tokens for onchain checks; it cannot prove exhaustive absence of
  foreign ERC1155 holdings. Use a dedicated wallet and preserve the ledger through restarts.
- 2026-09-06: A SELL uses verified current tick metadata; the historical entry tick is not
  immutable. A current disagreement permits only the documented supported finer/dividing SDK
  grid with protected prices. See docs/research/tick-change-contract.md for the actual vectors.
- 2026-09-06: Entry confirmation is a prospective experiment motivated by one information-lag
  event. Wait for a strictly newer spot source to reach the original book timestamp, then use
  the current eligible decision. Cancel observed invalidations; no reservation while waiting.
  Current books can still lead, and the event does not prove this better than a second check.
- 2026-09-06: Native WSL/Linux is the verified runtime target. Docker Desktop's shim is present
  but WSL integration is unavailable; remove the old launcher rather than advertise an untested
  replacement container workflow. Preserve feature branches/worktrees for the user to merge.
- 2026-09-06: Once a whole-position STOP/PROFIT condition requests a close, keep that request
  active across partial fills, changing quotes and restart. Continue protected current partial
  attempts when safe, retain the original reason, and never confuse a trigger with a guaranteed
  price or successful sale. This resolves an ambiguous policy, not an optimized-return claim.
- 2026-09-06: Manual reconciliation is read-only at the venue but writes local execution evidence,
  so it takes the same journal-owner lock as trading. Readonly status/report/account diagnosis
  and the dedicated concurrent stop writer remain available while the trader owns the journal.

- 2026-09-06: The additional article's valuation and inventory principles are useful, but its
  private algorithms and10M-execution dataset are unverified. Public API checks confirm named
  account profits; they do not prove causal strategy attribution. The AdanaKebab screenshots are
  separate from Daniro's August19 article. Current V2 fees are cash-additive for BUY, not the old
  V1 share-deducted model. A332-book-pair quote comparison found no complementary-exit advantage;
  defer that extra machinery and six funded portfolios. See inventory-strategy-ruling.md.
