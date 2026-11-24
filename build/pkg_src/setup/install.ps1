# LightDeck installer: copies the app to your user Programs folder and adds shortcuts.
# No admin rights needed. Updating keeps your settings (config.json) and your own effects.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$app = Join-Path $root 'LightDeck'
$dst = Join-Path $env:LOCALAPPDATA 'Programs\LightDeck'

Write-Host ''
Write-Host '  LightDeck installer' -ForegroundColor Cyan
Write-Host "  Installing to $dst"
Write-Host ''

if (-not (Test-Path (Join-Path $app 'LightDeck.exe'))) {
    Write-Host '  Could not find LightDeck\LightDeck.exe next to this installer.' -ForegroundColor Red
    Write-Host '  Extract the whole zip first, then run "Install LightDeck" from the extracted folder.'
    exit 1
}

$running = Get-Process LightDeck -ErrorAction SilentlyContinue
if ($running) {
    Write-Host '  Closing the running LightDeck...'
    $running | ForEach-Object { $null = $_.CloseMainWindow() }
    Start-Sleep 3
    Get-Process LightDeck -ErrorAction SilentlyContinue | Stop-Process -Force
}

New-Item -ItemType Directory -Force $dst | Out-Null
# copy everything except an existing config.json (keeps your settings on update)
$null = robocopy $app $dst /E /XF config.json /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { Write-Host '  Copying failed.' -ForegroundColor Red; exit 1 }

$ws = New-Object -ComObject WScript.Shell
$links = @(
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\LightDeck.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'LightDeck.lnk')
)
foreach ($lnk in $links) {
    $s = $ws.CreateShortcut($lnk)
    $s.TargetPath = Join-Path $dst 'LightDeck.exe'
    $s.WorkingDirectory = $dst
    $s.IconLocation = Join-Path $dst 'lightdeck.ico'
    $s.Description = 'LightDeck RGB controller'
    $s.Save()
}

# Start with Windows? (same registry value the app's Settings switch uses)
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$approvedKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
$already = $null -ne (Get-ItemProperty $runKey -Name LightDeck -ErrorAction SilentlyContinue)
Write-Host ''
if ($already) {
    $answer = Read-Host '  Keep starting LightDeck when Windows starts? (Y/n)'
    $wantStartup = -not ($answer -match '^\s*n')
} else {
    $answer = Read-Host '  Start LightDeck automatically when Windows starts? (y/N)'
    $wantStartup = $answer -match '^\s*y'
}
if ($wantStartup) {
    New-Item -Path $runKey -Force -ErrorAction SilentlyContinue | Out-Null
    Set-ItemProperty $runKey -Name LightDeck -Value ('"' + (Join-Path $dst 'LightDeck.exe') + '" --startup')
    Remove-ItemProperty $approvedKey -Name LightDeck -ErrorAction SilentlyContinue
    Write-Host '  LightDeck will start with Windows (minimized). Change it any time in LightDeck > Settings.'
} else {
    Remove-ItemProperty $runKey -Name LightDeck -ErrorAction SilentlyContinue
    Remove-ItemProperty $approvedKey -Name LightDeck -ErrorAction SilentlyContinue
    Write-Host '  OK, not starting with Windows. You can turn it on later in LightDeck > Settings.'
}
Write-Host ''

Write-Host '  Done! Shortcuts added to the Start menu and Desktop.' -ForegroundColor Green
Write-Host '  Close other RGB apps (SignalRGB, iCUE, Armoury Crate...) before using LightDeck.'
Write-Host ''
Start-Process (Join-Path $dst 'LightDeck.exe') -WorkingDirectory $dst
Start-Sleep 2
