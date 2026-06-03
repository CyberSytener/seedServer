param(
    [string]$LogDir = "logs/public",
    [int]$RetentionDays = 7,
    [int]$MaxFileSizeMB = 50
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$resolvedLogDir = Join-Path $projectRoot $LogDir

if (-not (Test-Path $resolvedLogDir)) {
    New-Item -Path $resolvedLogDir -ItemType Directory -Force | Out-Null
}

$maxBytes = $MaxFileSizeMB * 1MB
$timestamp = Get-Date -Format "yyyyMMddHHmmss"

$rotatedCount = 0
$deletedCount = 0

Get-ChildItem -Path $resolvedLogDir -File -Filter "*.log" | ForEach-Object {
    if ($_.Length -gt $maxBytes) {
        $archiveName = "{0}.{1}.log" -f $_.BaseName, $timestamp
        $archivePath = Join-Path $resolvedLogDir $archiveName
        Move-Item -Path $_.FullName -Destination $archivePath -Force
        New-Item -Path $_.FullName -ItemType File -Force | Out-Null
        $rotatedCount++
    }
}

$cutoff = (Get-Date).AddDays(-1 * $RetentionDays)
Get-ChildItem -Path $resolvedLogDir -File | Where-Object { $_.LastWriteTime -lt $cutoff } | ForEach-Object {
    Remove-Item -Path $_.FullName -Force
    $deletedCount++
}

Write-Host "Log rotation complete." -ForegroundColor Green
Write-Host "Rotated files: $rotatedCount"
Write-Host "Deleted old files: $deletedCount"
Write-Host "Log directory: $resolvedLogDir"
