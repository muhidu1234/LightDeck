# Records USB traffic on every USB controller until stop.txt appears in this folder.
# Run elevated (USBPcap needs admin). Only records; it never sends anything to devices.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cmd = "C:\Program Files\USBPcap\USBPcapCMD.exe"
Remove-Item "$here\stop.txt", "$here\started.txt", "$here\stopped.txt", "$here\hub*.pcap" -ErrorAction SilentlyContinue
$procs = @()
foreach ($i in 1..5) {
    $procs += Start-Process $cmd -ArgumentList "-d", "\\.\USBPcap$i", "-o", "`"$here\hub$i.pcap`"", "-A", "--inject-descriptors" -PassThru -WindowStyle Hidden
}
"started $(Get-Date -Format o)" | Out-File "$here\started.txt"
$deadline = (Get-Date).AddMinutes(30)   # safety: never record longer than 30 minutes
while (-not (Test-Path "$here\stop.txt") -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
Start-Sleep 1
$procs | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
"stopped $(Get-Date -Format o)" | Out-File "$here\stopped.txt"
