# Unattended BTC development

This project reuses only the Codex/Claude execution, failure classification and verification semaphore
helpers pinned to `405ae9d2c1f3808af7c773ebb8880e88283f1207` in the local
`~/projects/autopilot` repository. It does not run Alpha-Sentry's phase scheduler or merge code.
The assigned worktree is `.worktrees/autopilot`, branch `chore/btc-autopilot`. All pushes and
PRs target `viliusjask/5min-btc-polymarket` through **fork**, never upstream **origin**.
The user handles all merges, including integration. Existing services and data are untouched.

Write the authorized objective to the ignored `.autopilot/INBOX.md` in this worktree first.
No unfinished authorized work means idle, not an invented new objective. Then run:

```bash
bash scripts/autopilot.sh preflight
bash scripts/autopilot.sh start
bash scripts/autopilot.sh status
```

The dedicated tmux session is `btc5m-autopilot`. `stop` finishes the current model call;
`halt` also terminates the matching runner and its child processes. `resume` wakes an idle
running session after its inbox or external prerequisites change; a stopped session needs
`start`. There is no deadline. Start does not run a paid model probe; preflight checks local
executables, pinned helpers, fork access and existing hook dispatcher. Both Codex and Claude CLIs must be available. Model failures are
classified during execution. Secrets are not read or copied.

The durable cycle starts with full research re-planning despite completed historical plans:

- PLAN: Fable 5.1 medium author → Astra high independent review → Fable corrections and fresh
  Astra review until approved.
- BUILD: Opus 4.8 medium author → Astra high independent review → Opus corrections and fresh
  Astra review until approved → wrapper-run full project gate.
- INTEGRATION: Fable 5.1 high reviews the complete cumulative diff. Findings go to Astra high
  fixes, then a separate fresh Astra high reviewer until approved. Clean initial Fable review
  may proceed directly to verification. Gate failures also require Astra fixes and rereview.

The final integration gate reruns the full suite on exact reviewed commits before completion.
This runner is serial in one feature worktree, not Alpha-Sentry's parallel phase scheduler. A successful increment continues BUILD; completion
or unavailable external prerequisites idle until resume. Scope changes after a completed task
should start a fresh PLAN by setting `.autopilot/mode` to `PLAN` and `.autopilot/stage` to `author`
while stopped, then replacing the inbox. Do not replace an active objective mid-review.

Authors have full filesystem access and approval policy never; Astra reviewers use a read-only
sandbox and Fable integration review receives Read/Glob/Grep tools with local diff/PR snapshots. Prompts restrict authors to assigned development scope,
no financial/account actions and no service changes. This is not operating-system isolation
for author sessions. The wrapper requires clean committed work and a pushed matching branch.
Review approval binds exact HEAD and fork/main commits. BUILD approval also requires the
wrapper to run lock validation, all pytest tests, Ruff lint/format, mypy and shell syntax checks,
then recheck clean HEAD/base/remote identity before recording `.autopilot/verified`.

The gate uses the shared `~/projects/autopilot/state/verification` directory with two slots
across BTC and Alpha-Sentry. Failed verification logs go back to the author. Rate limits retry
after ten minutes; authentication failures and repeated failures idle without model polling.
Three author attempts without a new checkpoint also idle. State, reviews, effective prompts,
Codex events, gate logs and the local briefing live under ignored `.autopilot/` and survive
restart. No model fallback is authorized when limits occur. Reviewers cannot settle findings by author
response alone: every changed plan/build/integration
receives a fresh independent review. All commits remain in a draft PR for user review/merge.

## Research scope

The objective is to find whether a defensibly profitable subset of automated short-term,
high-volatility/day-trading strategies can run as background bots. Re-plan from that objective,
using in-depth cited research and extensive strategy testing. The plan must define baseline
comparisons, fees, slippage, latency, conservative fills, chronological held-out evaluation,
multiple-testing discipline, uncertainty and negative results. Historical implementation and
paper profits are not proof of profitability. Public data and synthetic account fixtures only;
no live-funded trading, service changes or credential access is authorized. The exact working
objective is in ignored `.autopilot/INBOX.md`.

Startup inventories all local branches and dirty worktrees through the pinned shared
`scripts/wip_preflight.py`. Missing or stale dispositions reopen PLAN recovery automatically;
they do not silently select fork/main or require a human checkpoint. The author reconciles
relevant existing work into its assigned branch, records exact evidence in
`.autopilot/wip-dispositions.json`, and revises the plan for fresh Astra review. Original
worktrees and runtime data remain intact. New source work is still gated by plan approval.

Author conversations persist through correction/quota rounds using a stable stage key in
`.autopilot/author-session-stage.json`; timestamped log names do not create new author
conversations. PLAN, BUILD and INTEGRATION authors have distinct stage keys. The shared
runner binds sessions to worktree, branch, model and effort and rotates overly large contexts.
Resumed prompts carry current findings and task changes. Reviewers always start separately
and freshly; every approving review covers the cumulative current change. Subagent delegation
remains allowed. Stage/session records and old transcripts are retained for recovery.


Claude authors now use medium effort and retain conversations across effort-only changes.
Native compaction triggers at 40% of the effective context window (about 400k with the assigned
1M models); between-invocation rotation is 500k. Durable author handoffs preserve current
findings, decisions, verification and next actions. Two top-level Claude invocations share
slots with Alpha; delegated agents remain permitted. `.autopilot/usage/` keeps immutable
per-attempt usage and tool-call receipts, including incomplete calls. Serena read-only symbol
tools are explicitly available to Claude reviewers. Claude calls use the shared Headroom
helper with a private per-invocation loopback proxy, cache-preserving lossless output
compression, protected source reads and unchanged subscription authentication. The `[1m]`
CLI model suffix retains the context window; API model IDs remain unchanged. Operational
logs and aggregate metrics live in `.autopilot/headroom/<stage>/<uuid>/`. Originals remain
in Claude transcripts. Proxy failure is visible; no silent direct-routing fallback.
