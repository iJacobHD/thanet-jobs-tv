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

    Write-Host "Downloading the latest job slides..."
    Invoke-WebRequest -Uri "$Site/usb/slides.zip?t=$([DateTime]::Now.Ticks)" -OutFile $tmp -UseBasicParsing

    if (Test-Path $dest) { Get-ChildItem $dest -Filter "JOBS_*.jpg" | Remove-Item -Force }
    else { New-Item -ItemType Directory -Path $dest | Out-Null }
    Expand-Archive -Path $tmp -DestinationPath $dest -Force
    Remove-Item $tmp -Force

    $n = (Get-ChildItem $dest -Filter "JOBS_*.jpg").Count
    Write-Host ""
    Write-Host "Done: $n slides are in $dest" -ForegroundColor Green
    Write-Host "Safely eject the stick, put it in the TV and start the photo slideshow from the JOBS folder."
} catch {
    Write-Host ""
    Write-Host "Something went wrong: $($_.Exception.Message)" -ForegroundColor Red
}
Read-Host "Press Enter to close"
