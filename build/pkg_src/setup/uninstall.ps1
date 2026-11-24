# LightDeck uninstaller: removes the app and its shortcuts.
$dst = Join-Path $env:LOCALAPPDATA 'Programs\LightDeck'
$userData = Join-Path $env:APPDATA 'LightDeck'

Write-Host ''
Write-Host '  LightDeck uninstaller' -ForegroundColor Cyan
Write-Host "  This removes $dst (including your LightDeck settings and effects) and the shortcuts."
$answer = Read-Host '  Type Y and press Enter to uninstall'
if ($answer -ne 'Y' -and $answer -ne 'y') { Write-Host '  Cancelled.'; Start-Sleep 2; exit 0 }

Get-Process LightDeck -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1
# OpenRGB started by LightDeck runs from inside the app folder
Get-Process OpenRGB -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$dst*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 1

Remove-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name LightDeck -ErrorAction SilentlyContinue
Remove-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run' -Name LightDeck -ErrorAction SilentlyContinue
Remove-Item (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\LightDeck.lnk') -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) 'LightDeck.lnk') -ErrorAction SilentlyContinue
Remove-Item $dst -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $userData) { Remove-Item $userData -Recurse -Force -ErrorAction SilentlyContinue }

if (Test-Path $dst) {
    Write-Host '  Some files could not be removed (OpenRGB may still be running as admin).' -ForegroundColor Yellow
    Write-Host "  Close OpenRGB and delete $dst by hand."
} else {
    Write-Host '  LightDeck was removed.' -ForegroundColor Green
}
Write-Host '  (OpenRGB keeps its own small settings folder in %APPDATA%\OpenRGB - delete it if you like.)'
Start-Sleep 4
