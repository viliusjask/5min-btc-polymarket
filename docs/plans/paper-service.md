# Continuous paper service and interruption recovery

Keep the existing six USD100 portfolios and all committed records. Add an explicit continuous
paper mode, supervised independently from Codex by the existing systemd user manager. Install
a Windows task that launches Ubuntu on login and retries after WSL termination; keep a Windows
WSL client attached because systemd services alone do not keep WSL running. Do not change Windows
sleep policy, restart WSL for testing, or introduce funded actions.

1. Add mutually exclusive finite/continuous paper CLI options. Preserve explicit loss caps and
   stop requests. Add service readiness/heartbeat notification, bounded cleanup, and atomic
   report/manifest writes. Keep live CLI duration mandatory.
2. Exercise abrupt interruption around persisted fills and accounting application. Recover
   committed paper fills exactly once; invalidate incomplete queue/late immediate orders after
   observation gaps. Record affected rounds as uncertain without deleting balances or orders.
3. Install reproducible systemd paper/dashboard services with restart supervision, user lingering,
   private persistent runtime/config paths, and a Windows launcher with explicit stop controls.
   Operational logs may use the system journal; public observations and trading evidence remain
   in the application SQLite journals, which are not pruned.
4. Test outage/reconnect, process kill/restart, signal shutdown, duplicate owner exclusion and
   Windows launcher registration. Simulate PC/WSL death with a dedicated test process; never kill
   the user's WSL or sleep the machine during verification.
5. Cut over once from the old collector, preserving its database histories and funds. Point the
   supervised dashboard at the same persistent runtime. Verify services survive their launcher
   exiting and notify the operator of unavoidable capture gaps while the machine is offline.
6. Update operator commands and cheatsheet, commit/push/open a PR, and leave services running.

SQLite FULL synchronous WAL commits protect committed records against process interruption.
SIGKILL/power loss cannot execute cleanup; uncommitted work may be rolled back, and observations
that never arrived while offline cannot be recovered or silently invented. Disk/hardware failure
is outside a zero-loss guarantee. Local trading pauses while the PC sleeps and resumes after wake.

The later zero-fill report expanded the execution investigation: correct complementary BUY flow,
retain and deduplicate public transaction identity, show actual execution outcomes, and label
historical orders from the earlier model. A real captured-order replay is documented in
`docs/research/paper-fill-diagnosis.md`; do not inject its counterfactual fills into the running
portfolios. Entry/cancellation policy changes remain separate from this simulator repair.
