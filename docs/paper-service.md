# Continuous paper trading on WSL

The September 7 setup runs all six portfolios with **USD100 each**. The collector and dashboard
are systemd user services, supervised independently from Codex, terminals and browser tabs.
The collector uses `paper --continuous`; funded trading is not started. There is no daily
entry-count limit (`max_entries_per_day = 0`). Loss allowances and per-entry budgets still apply.

## Installed locations and controls

- Collector and dashboard code: `/home/vilius/projects/5min-btc-polymarket/.worktrees/strategy-policy-audit`
  (`fix/strategy-policy-audit`, [PR12](https://github.com/viliusjask/5min-btc-polymarket/pull/12)).
- The original registered lab remains on `.worktrees/experiment-lab`; the 17-variant
  order-flow study remains on `.worktrees/order-flow`. Keep these three active checkouts.
- Data: `/home/vilius/.local/share/btc5m/paper-six-100-each` — master observations plus six SQLite journals.
- Collector/dashboard configuration: `/home/vilius/.config/btc5m/paper-strategy-policy.toml` —
  USD600 allocation, USD5 entry budget, USD10 day/session loss allowance per portfolio.
  Momentum follows the 30-second recent move relative to five-minute price variation;
  the Value-family price floor remains disabled. Sessions and balances persist across restarts.
- Both pinned lab workers still use `/home/vilius/.config/btc5m/paper.toml`, byte-for-byte
  unchanged. Do not give these old workers the new configuration schema.
- Units: `~/.config/systemd/user/btc5m-paper.service` and `btc5m-dashboard.service`.
- Dashboard: [localhost:8765](http://127.0.0.1:8765/). Real view remains read-only and explicitly
  references the canonical ignored `.env`; the collector has no account credentials.
- Windows: Task Scheduler `BTC5m-WSL`, script `%LOCALAPPDATA%\BTC5m\keep-wsl.ps1`,
  launcher log `%LOCALAPPDATA%\BTC5m\launcher.log`.

Run in Ubuntu/WSL:

```bash
systemctl --user status btc5m-paper.service btc5m-dashboard.service
journalctl --user -u btc5m-paper.service -n 50 --no-pager
systemctl --user stop btc5m-paper.service
systemctl --user start btc5m-paper.service
systemctl --user restart btc5m-dashboard.service
```

`systemctl stop` is intentional and does not trigger automatic restart. The paper stop requests
cancellation and monitors existing exposure for up to 60 seconds; transport cleanup is bounded
at 10 seconds. The supervisor allows 90 seconds before forced termination. Unresolved positions
remain recorded and resume reconciliation on an explicit start. Use the same runtime/config;
creating another directory creates another experiment. Never copy a live SQLite file alone:
stop its collector before copying the entire runtime, or use SQLite's online backup API.

To disable automatic launch, disable both user units and the Windows task. In PowerShell:

```powershell
Disable-ScheduledTask -TaskName 'BTC5m-WSL'
Stop-ScheduledTask -TaskName 'BTC5m-WSL'
# To restore the Windows launcher:
Enable-ScheduledTask -TaskName 'BTC5m-WSL'
Start-ScheduledTask -TaskName 'BTC5m-WSL'
```

## Sleep, network loss and termination

While Windows is logged in, the hidden launcher owns a WSL client and retries ten seconds after
that client exits. It also starts at Windows login. Enabled user services start when Ubuntu boots;
user lingering is enabled. [Microsoft documents](https://learn.microsoft.com/en-us/windows/wsl/systemd)
that systemd services alone do not keep a WSL instance alive, hence the Windows-owned client.
Logging out ends this interactive Windows task; it resumes at the next login. No sleep policy was changed.

The collector reconnects public feeds after internet loss. Freshness checks prevent entries on
stale inputs. After PC sleep or a stalled execution loop, it records an interruption, invalidates
unfinished simulated execution and marks affected positions uncertain. New stream sessions also
invalidate incomplete paper orders, including orders interrupted before initial queue activation.
Committed fills remain authoritative and are applied to accounting once.

Nothing local trades while the PC sleeps, is off, or has no market connection. Sleep normally
pauses the process; SIGKILL/WSL termination/power loss cannot execute graceful cleanup. SQLite uses
FULL synchronous WAL commits: committed records recover, incomplete transactions roll back, and
unreceived observations cannot be recreated. This is not a disk/hardware failure backup guarantee.

No observations or trading history are automatically deleted. Startup and minute checks stop
capture when free space falls below 256 MiB; the supervisor retries failed starts every ten
seconds. This is a reserve check, not a hard disk quota. At the initial capture rate raw data can
grow by several GB/day, so check disk usage and keep independent backups for long runs.

## Reinstall after a checkout change

When the [experiment lab](experiment-lab.md) is enabled, also manage `btc5m-lab.service`.
Pass `--lab` only when its registered implementation matches the target checkout.
For the separate [order-flow study](order-flow.md), use `--order-flow` and manage
`btc5m-flow-lab.service` only when that worker's registered implementation matches the checkout;
preserve both existing lab units on their registered checkouts. Its input
tape and study registry retain FULL durability; its derived replay journals use recoverable
WAL/NORMAL caches. The original portfolio journals retain the durability described above.
An unchanged semantic code identity can resume a registered study after a merge. A code change
requires a preserved, separate study rather than silently mixing implementations.

For a dashboard-only update, change only its `WorkingDirectory` and `ExecStart` checkout paths,
verify with an isolated temporary `XDG_RUNTIME_DIR`, then reload units and restart only
`btc5m-dashboard.service`. PR11 used this operation: the collector and both study process ids,
both registration hashes and all six portfolio sessions remained unchanged. The Real view's
existing explicit account-file path is preserved without reading that file.

For an update that also changes the collector, preserve both
study units and the collector's `--capture-flow` argument. Change only the checkout paths
in `WorkingDirectory` and `ExecStart` for `btc5m-paper` and `btc5m-dashboard`, then run
`systemctl --user daemon-reload` and restart those two services. PR10 used this operation,
with both study process ids and manifests checked before/after. The generic installer below
without `--order-flow` would remove flow capture; adding `--order-flow` would repoint its
worker. Neither is appropriate for a collector-only update while studies are pinned.

For a new basic six-portfolio installation without a registered flow study, run
`uv sync --locked` in the intended feature checkout, then:

```bash
.venv/bin/python scripts/install_paper_service.py \
  --runtime /home/vilius/.local/share/btc5m/paper-six-100-each \
  --config /home/vilius/.config/btc5m/paper.toml \
  --env-file /home/vilius/projects/5min-btc-polymarket/.env
systemctl --user restart btc5m-paper.service btc5m-dashboard.service
loginctl enable-linger "$USER"
```

The installer never reads the account file. It verifies units with an isolated temporary
`XDG_RUNTIME_DIR`: systemd 249's user verifier can replace live manager sockets when run against
the real runtime. A regression checks this isolation. The script enables services without starting
or stopping existing owners; the restart above is the explicit cutover. Preserve this checkout
until the units have been repointed after merging.

## Capture quality and experiment profit

Experiments shows all realized profit, completed unflagged profit and the excluded remainder
together. The remainder can include realized amounts on incomplete rounds; held cost appears
separately. Unflagged means no recorded warning, not validated profitability.

New capture diagnostics distinguish rejected snapshots from intervals longer than the
configured recorder-gap limit. Cause counts record the first failed check, not every possible
upstream fault. Their start time is explicit: old generic gap flags are not reclassified.
The bounded counter record commits atomically inside `capture.sqlite`; restarts retain it.
The dashboard reads it without modifying either registered study or its report. See the
[reversal audit](research/reversal-evidence-audit.md) for the historical reconstruction.

**Experiments → Strategy research** adds profit distributions, outlier/cost sensitivity,
entry-condition breakdowns, hourly contributions and comparisons on the same markets for
the existing84+17variants. It reads the journals independently of the trading workers.
The [research guide](research/strategy-comparisons.md) explains the calculations and limits.

For the Windows task, copy `scripts/windows/*.ps1` to a local Windows directory, then run
`install-wsl-task.ps1 -Distribution Ubuntu -LinuxUser vilius` in PowerShell. The installer copies
the launcher into LocalAppData and registers/starts a current-user task. It needs no API keys.

## Strategy-policy cutover, September 7

The corrected collector/dashboard started at approximately 18:44 UTC. All seven session IDs
(master plus six portfolios), six balances, historical orders/fills/accounting, and accumulated
session/day losses were verified preserved. Full backups were verified online before stopping
owners; the bounded metadata-only migration used fresh financial-state checks and appended
`CONFIGURATION_CHANGED` records with baselines. It did not restore stale financial rows.
The largest captured interruption was 73.950 seconds, including graceful shutdown/reporting
and startup. Restored history retained its original timestamps; five-minute sampling must
recover its coverage instead of inventing observations during that gap.

The original tape prefix/checksum was verified unchanged and new frames advanced. Both lab
PIDs, unit files, configuration and registration hashes were preserved. Code validation passed
681 tests; PR12 CI passed. The dashboard marks the cutover and explains that lifetime totals
include the earlier policies. Further deployment details and backups remain in the active
checkout's ignored `work/deployment/` and `work/value-audit/policy-migration/` directories.

## Independent market refresh and book recovery

The metadata-refresh repair separates settlement-result polling from current-market HTTP
refreshes. A slow delayed result no longer holds the refresh lock. The settlement task is
cancelled and joined with the other feed tasks during shutdown. Market settings retain their
five-second validation lifetime; price and book source/receipt timestamps are never renewed
by cache reuse. A valid settings response can be retained while the BTC price feed recovers.

Book transport interruptions now require synchronized depth without expiring market settings.
Cached REST depth from before an interruption cannot be reused, and a response completed after
a newer invalidation cannot restore it. Tick changes require fresh authoritative metadata; supported coarse headers may be accepted
only under the documented dividing-grid refinement with compatible actual prices. Other
inconsistent venue settings remain rejected. The CLI immediately invalidates prepared-entry input on book failure.

Capture diagnostics distinguish `METADATA_INVALIDATED`, with its original reason, from actual
`METADATA_CACHE_EXPIRED` and `BOOK_RESYNC_PENDING`. The dashboard shows settings age and the
latest underlying reason. Historical expiry counts include the old collector's mixed meanings;
they remain intact. Ratios in the cause table use rejected samples, not every sample or trade.
No runtime configuration, accounting schema, wallet session, or study registration changes are
required for this code-only restart. Both study workers retain their registered checkouts.
