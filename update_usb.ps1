# Thanet Jobs TV - copy the latest job slides onto the USB stick.
# ===== EDIT THIS LINE ONCE (your GitHub Pages address) =====
$Site = "https://ijacobhd.github.io/thanet-jobs-tv"
# ===========================================================
$ErrorActionPreference = "Stop"
try {
    $sticks = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=2")
    if ($sticks.Count -eq 0) { throw "No USB stick found. Plug it in and try again." }
    $drive = $sticks[0].DeviceID
    if ($sticks.Count -gt 1) {
        Write-Host "More than one USB drive found: $($sticks.DeviceID -join ', ')"
        $drive = (Read-Host "Type the drive letter to use (e.g. E)").Trim().TrimEnd(':') + ":"
    }
    $dest = "$drive\JOBS"
    $tmp  = Join-Path $env:TEMP "thanet-slides.zip"

    Write-Host "Downloading Jobs this week.mp4 ..."
    if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest | Out-Null }
    $tmpVideo = Join-Path $env:TEMP "jobs-this-week.mp4"
    Invoke-WebRequest -Uri "$Site/usb/jobs-this-week.mp4?t=$([DateTime]::Now.Ticks)" -OutFile $tmpVideo -UseBasicParsing
    Copy-Item $tmpVideo (Join-Path $dest "Jobs this week.mp4") -Force
    Remove-Item $tmpVideo -Force

    Write-Host ""
    Write-Host "Done: $dest\Jobs this week.mp4 is up to date" -ForegroundColor Green
    Write-Host "Safely eject the stick, put it in the TV and play the video with repeat on."
} catch {
    Write-Host ""
    Write-Host "Something went wrong: $($_.Exception.Message)" -ForegroundColor Red
}
Read-Host "Press Enter to close"
