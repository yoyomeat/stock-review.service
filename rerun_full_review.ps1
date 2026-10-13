# Full review PowerShell script
# Usage: .\rerun_full_review.ps1

param(
    [string]$StartDate = "",
    [string]$EndDate = ""
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$ErrorActionPreference = "Continue"
$SkillDir = $PSScriptRoot
$CsvDir = Join-Path $SkillDir "data\csv"
$LogDir = Join-Path $SkillDir "logs"

if (!(Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$LogFile = Join-Path $LogDir ("rerun_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

# 清空sentiment cache，确保重跑结果可复现
$CacheFile = Join-Path $SkillDir "data\daily_sentiment_cache.json"
if (Test-Path $CacheFile) {
    Set-Content -Path $CacheFile -Value "[]" -Encoding utf8
    Write-Host "Sentiment cache cleared" -ForegroundColor Yellow
}

$csvFiles = Get-ChildItem -Path $CsvDir -Filter "stock_daily_*.csv" | Sort-Object Name
$Total = $csvFiles.Count

if ($Total -eq 0) {
    Write-Host "No CSV files found" -ForegroundColor Red
    exit 1
}

$OK = 0
$FAIL = 0
$Count = 0
$Skipped = 0
$StartTime = Get-Date

Write-Host "=== Review started ($Total dates) ===" -ForegroundColor Cyan

foreach ($csv in $csvFiles) {
    $Count++
    $Date = $csv.Name -replace "stock_daily_", "" -replace "\.csv", ""

    if ($StartDate -and $Date -lt $StartDate) { $Skipped++; continue }
    if ($EndDate -and $Date -gt $EndDate) { $Skipped++; continue }

    $pct = [math]::Round($Count / $Total * 100)
    Write-Host -NoNewline ("[{0}/{1}] {2} ({3}%) ok={4} fail={5} " -f $Count, $Total, $Date, $pct, $OK, $FAIL)

    $output = & python run_review.py $Date --force --skip-download 2>&1
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        $OK++
        Write-Host "OK" -ForegroundColor Green
        $output | Out-File -FilePath $LogFile -Append -Encoding utf8
    } else {
        $FAIL++
        Write-Host "FAIL" -ForegroundColor Red
        "FAIL $Date" | Out-File -FilePath $LogFile -Append -Encoding utf8
        $output | Out-File -FilePath $LogFile -Append -Encoding utf8
    }
}

$Elapsed = (Get-Date) - $StartTime
Write-Host ""
Write-Host "=== Done: ok=$OK fail=$FAIL skip=$Skipped total=$Total elapsed=$([math]::Round($Elapsed.TotalMinutes,1))min ===" -ForegroundColor Green
"=== Done: ok=$OK fail=$FAIL skip=$Skipped total=$Total ===" | Out-File -FilePath $LogFile -Append -Encoding utf8
Write-Host "Log: $LogFile" -ForegroundColor Gray
