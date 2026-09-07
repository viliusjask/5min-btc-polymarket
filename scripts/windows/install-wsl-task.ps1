param(
    [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$Distribution = 'Ubuntu',
    [ValidatePattern('^[a-z_][a-z0-9_-]*$')][string]$LinuxUser = 'vilius'
)
$ErrorActionPreference = 'Stop'
$installDirectory = Join-Path $env:LOCALAPPDATA 'BTC5m'
New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
$launcher = Join-Path $installDirectory 'keep-wsl.ps1'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'keep-wsl.ps1') -Destination $launcher -Force
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy RemoteSigned -File "' + $launcher + '" -Distribution ' + $Distribution + ' -LinuxUser ' + $LinuxUser
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'BTC5m-WSL' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Keep Ubuntu available for BTC5m paper services; retry after WSL termination. No power-policy changes or funded trading.' -Force | Out-Null
Start-ScheduledTask -TaskName 'BTC5m-WSL'
Get-ScheduledTask -TaskName 'BTC5m-WSL' | Select-Object TaskName, State
