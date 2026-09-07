# Continuous paper trading on WSL

The September 7 setup runs all six portfolios with **USD100 each**. The collector and dashboard
are systemd user services, supervised independently from Codex, terminals and browser tabs.
The collector uses `paper --continuous`; funded trading is not started. There is no daily
entry-count limit (`max_entries_per_day = 0`). Loss allowances and per-entry budgets still apply.

## Installed locations and controls

- Code: `/home/vilius/projects/5min-btc-polymarket/.worktrees/limit-sizing` (`fix/limit-sizing`).
- Data: `/home/vilius/.local/share/btc5m/paper-six-100-each` — master observations plus six SQLite journals.
- Configuration: `/home/vilius/.config/btc5m/paper.toml` — USD600 allocation, USD5 entry budget,
  USD10 day/session loss allowance per portfolio. The Value-family price floor is disabled and
  Momentum requires aUSD50 lead. Restarting preserves sessions and balances.
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
Pass `--lab` to the installer below and include that service in the restart command. Its input
tape and study registry retain FULL durability; its derived replay journals use recoverable
WAL/NORMAL caches. The original portfolio journals retain the durability described above.
An unchanged semantic code identity can resume a registered study after a merge. A code change
requires a preserved, separate study rather than silently mixing implementations.

From the intended feature checkout, run `uv sync --locked`, then:

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

For the Windows task, copy `scripts/windows/*.ps1` to a local Windows directory, then run
`install-wsl-task.ps1 -Distribution Ubuntu -LinuxUser vilius` in PowerShell. The installer copies
the launcher into LocalAppData and registers/starts a current-user task. It needs no API keys.
