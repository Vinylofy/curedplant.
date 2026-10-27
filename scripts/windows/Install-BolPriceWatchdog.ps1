param(
    [switch]$ProbeOnly,
    [string]$PythonPath
)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$admin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$service = $identity.User.Value -in @('S-1-5-18','S-1-5-19','S-1-5-20')
$gh = Get-Command gh -ErrorAction SilentlyContinue
$authenticated = $false
if ($gh -and -not $env:GITHUB_TOKEN) {
    try {
        & $gh.Source auth status *> $null
        if ($LASTEXITCODE -eq 0) {
            & $gh.Source api 'repos/Vinylofy/curedplant./actions/workflows/price-bol-api.yml' *> $null
            $authenticated = $LASTEXITCODE -eq 0
        }
    } catch { $authenticated = $false }
}
$ready = [bool]($gh -and $authenticated -and $admin)
if ($ProbeOnly -or -not $ready) {
    @{status=$(if ($ready) {'ready_to_install'} else {'local_setup_required'});
      ready=$ready; gh_installed=[bool]$gh; gh_authenticated=$authenticated;
      administrator=$admin; service_account=$service; installed=$false} | ConvertTo-Json -Compress
    return
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) { throw 'A persistent Python executable is required' }
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is required' }
$directory = Join-Path $env:LOCALAPPDATA 'Vinylofy\BolPriceWatchdog'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$source = Join-Path (Split-Path $PSScriptRoot -Parent) 'workers\bol_price_watchdog.py'
$script = Join-Path $directory 'bol_price_watchdog.py'
Copy-Item -LiteralPath $source -Destination $script -Force
$result = Join-Path $directory 'last-result.json'
$arguments = '"' + $script + '" --dispatch --result-file "' + $result + '"'
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument $arguments -WorkingDirectory $directory
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -StartWhenAvailable
$logon = if ($service) {'ServiceAccount'} else {'Interactive'}
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType $logon -RunLevel Limited
Register-ScheduledTask -TaskName 'Vinylofy Bol price watchdog' -Action $action -Trigger $trigger -Settings $settings -Principal $taskPrincipal -Force | Out-Null
@{status='installed'; installed=$true; ready=$true; service_account=$service;
  requires_logged_in_user=(-not $service); interval_minutes=10} | ConvertTo-Json -Compress
