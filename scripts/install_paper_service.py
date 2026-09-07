#!/usr/bin/env python3
"""Install this checkout's paper/dashboard user services without touching account keys."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def quote(value, *, command=False):
    text = str(value)
    if any(c in text for c in ("\n", "\r", "\0")):
        raise ValueError("invalid service path")
    text = text.replace("%", "%%")
    if not command:
        return text  # WorkingDirectory is a single path, not an argv word.
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$") + '"'


def unit(checkout, runtime, config, *, dashboard=False, lab=False, port=8765, env_file=None):
    if dashboard and lab:
        raise ValueError("select one service role")
    command = [
        checkout / ".venv/bin/btc5m",
        "dashboard" if dashboard else "paper",
        "--runtime",
        runtime,
        "--config",
        config,
    ]
    command += (
        ["--port", str(port)]
        if dashboard
        else ["--strategies", "all", "--continuous", "--shutdown-seconds", "60"]
    )
    if lab:
        command = [
            checkout / ".venv/bin/btc5m",
            "lab",
            "run",
            "--runtime",
            runtime / "lab",
            "--config",
            config,
            "--source",
            runtime / "capture.sqlite",
            "--continuous",
        ]
    if dashboard and env_file:
        command += ["--account", "--env-file", env_file]
    return "\n".join(
        [
            "[Unit]",
            "Description=BTC5m "
            + (
                "read-only dashboard"
                if dashboard
                else "paper experiment lab"
                if lab
                else "continuous paper portfolios"
            ),
            "StartLimitIntervalSec=0",
            "",
            "[Service]",
            "Type=" + ("simple" if dashboard else "notify"),
            "WorkingDirectory=" + quote(checkout),
            "ExecStart=" + " ".join(quote(value, command=True) for value in command),
            "Restart=on-failure",
            "RestartSec=10",
            "TimeoutStartSec=" + ("300" if lab else "120"),
            "TimeoutStopSec=90",
            "KillSignal=SIGTERM",
            "KillMode=control-group",
            "UMask=0077",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "Environment=PYTHONDONTWRITEBYTECODE=1",
            "StandardOutput=journal",
            "StandardError=journal",
            "SyslogIdentifier=btc5m-" + ("dashboard" if dashboard else "lab" if lab else "paper"),
            *(
                []
                if dashboard
                else [
                    "NotifyAccess=main",
                    "WatchdogSec=120",
                    "WatchdogSignal=SIGTERM",
                    "TimeoutAbortSec=90",
                ]
            ),
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--env-file",
        type=Path,
        help="existing file for optional read-only Real dashboard; never read by installer",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--lab", action="store_true", help="also enable the public-data experiment worker"
    )
    args = parser.parse_args()
    checkout = Path(__file__).resolve().parents[1]
    runtime, config = args.runtime.resolve(), args.config.resolve()
    if not config.is_file() or not (runtime / "paper.json").is_file():
        parser.error("select an existing paper runtime and configuration")
    manifest = json.loads((runtime / "paper.json").read_text())
    if manifest.get("environment") != "paper" or manifest.get("version") != 1:
        parser.error("paper runtime required")
    if not 1 <= args.port <= 65535:
        parser.error("invalid port")
    if args.lab and not (runtime / "capture.sqlite").is_file():
        parser.error("the paper collector must create capture.sqlite before enabling the lab")
    directory = Path.home() / ".config/systemd/user"
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    services = [("btc5m-paper", False, False), ("btc5m-dashboard", True, False)]
    if args.lab:
        services.append(("btc5m-lab", False, True))
    for name, dashboard, lab in services:
        target = directory / (name + ".service")
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            unit(
                checkout,
                runtime,
                config,
                dashboard=dashboard,
                lab=lab,
                port=args.port,
                env_file=args.env_file.resolve() if args.env_file else None,
            )
        )
        os.chmod(temporary, 0o600)
        temporary.replace(target)
    # Older systemd user verification creates manager sockets. Isolate its runtime
    # so a syntax check cannot replace the running user's control socket.
    with tempfile.TemporaryDirectory(prefix="btc5m-unit-check-") as verify_runtime:
        subprocess.run(
            [
                "systemd-analyze",
                "--user",
                "verify",
                *(str(directory / (name + ".service")) for name, _, _ in services),
            ],
            env={**os.environ, "XDG_RUNTIME_DIR": verify_runtime},
            check=True,
        )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "--user", "enable", *(name + ".service" for name, _, _ in services)],
        check=True,
    )
    print("Installed and enabled. Start after the previous owners release these journals/port:")
    print("systemctl --user start " + " ".join(name + ".service" for name, _, _ in services))


if __name__ == "__main__":
    main()
