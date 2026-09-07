param(
    [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$Distribution = 'Ubuntu',
    [ValidatePattern('^[a-z_][a-z0-9_-]*$')][string]$LinuxUser = 'vilius'
)
$ErrorActionPreference = 'Stop'
$launcherLog = Join-Path $PSScriptRoot 'launcher.log'
while ($true) {
    try {
        Add-Content -LiteralPath $launcherLog -Value ((Get-Date).ToUniversalTime().ToString('o') + ' WSL client starting')
        # A Windows-owned WSL client keeps the instance alive independently from Codex.
        # Enabled systemd user units start when Ubuntu boots; this does not override manual stops.
        & "$env:SystemRoot\System32\wsl.exe" --distribution $Distribution --user $LinuxUser --exec /bin/sleep infinity 2>> $launcherLog
        Add-Content -LiteralPath $launcherLog -Value ((Get-Date).ToUniversalTime().ToString('o') + " WSL client exited: $LASTEXITCODE")
    } catch {
        Add-Content -LiteralPath $launcherLog -Value ((Get-Date).ToUniversalTime().ToString('o') + ' WSL client launch failed; retrying')
    }
    Start-Sleep -Seconds 10
}
