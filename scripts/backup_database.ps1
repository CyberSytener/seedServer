# Database Backup Script for Seed Server (Windows PowerShell)
# Performs backup of SQLite database with rotation and compression

param(
    [string]$DatabasePath = "",
    [string]$BackupDir = "",
    [int]$MaxBackups = 30
)

# Configuration
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

if (-not $DatabasePath) {
    $DbUrl = $env:DATABASE_URL
    if ($DbUrl) {
        $DatabasePath = $DbUrl -replace '^sqlite:///', ''
    } else {
        $DatabasePath = Join-Path $ProjectRoot "data\seed_server.db"
    }
}

if (-not $BackupDir) {
    $BackupDir = Join-Path $ProjectRoot "data\backups"
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupName = "seed_server_$Timestamp.db"
$BackupPath = Join-Path $BackupDir $BackupName

# Helper functions
function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

# Create backup directory
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

# Check if database exists
if (-not (Test-Path $DatabasePath)) {
    Write-Error-Custom "Database not found at: $DatabasePath"
    exit 1
}

Write-Info "Starting database backup..."
Write-Info "Source: $DatabasePath"
Write-Info "Destination: $BackupPath"

# Check for sqlite3.exe
$Sqlite3Path = Get-Command sqlite3.exe -ErrorAction SilentlyContinue
if (-not $Sqlite3Path) {
    Write-Warn "sqlite3.exe not found in PATH. Using file copy method."
    # Fallback to simple copy
    Copy-Item -Path $DatabasePath -Destination $BackupPath -Force
} else {
    # Use SQLite backup command
    $BackupCommand = ".backup '$BackupPath'"
    $BackupCommand | sqlite3.exe $DatabasePath
}

if (Test-Path $BackupPath) {
    $BackupSize = (Get-Item $BackupPath).Length
    $BackupSizeMB = [math]::Round($BackupSize / 1MB, 2)
    Write-Info "Backup created successfully: $BackupName"
    Write-Info "Backup size: $BackupSizeMB MB"
    
    # Compress backup
    Write-Info "Compressing backup..."
    Compress-Archive -Path $BackupPath -DestinationPath "$BackupPath.zip" -Force
    
    # Remove uncompressed backup
    Remove-Item $BackupPath
    
    $CompressedSize = (Get-Item "$BackupPath.zip").Length
    $CompressedSizeMB = [math]::Round($CompressedSize / 1MB, 2)
    Write-Info "Compressed size: $CompressedSizeMB MB"
    
    # Cleanup old backups
    Write-Info "Cleaning up old backups (keeping last $MaxBackups)..."
    Get-ChildItem -Path $BackupDir -Filter "seed_server_*.zip" | 
        Sort-Object LastWriteTime -Descending | 
        Select-Object -Skip $MaxBackups | 
        Remove-Item -Force
    
    $RemainingBackups = (Get-ChildItem -Path $BackupDir -Filter "seed_server_*.zip").Count
    Write-Info "Backup complete. Total backups: $RemainingBackups"
    
    # Verify backup integrity (if sqlite3 available)
    if ($Sqlite3Path) {
        Write-Info "Verifying backup integrity..."
        $TempDb = Join-Path $env:TEMP $BackupName
        Expand-Archive -Path "$BackupPath.zip" -DestinationPath $env:TEMP -Force
        
        $IntegrityCheck = "PRAGMA integrity_check;" | sqlite3.exe $TempDb
        
        if ($IntegrityCheck -eq "ok") {
            Write-Info "Backup integrity verified: OK"
        } else {
            Write-Error-Custom "Backup integrity check failed: $IntegrityCheck"
            Remove-Item $TempDb -Force
            exit 1
        }
        
        Remove-Item $TempDb -Force
    }
    
    Write-Info "Backup completed successfully!"
    exit 0
    
} else {
    Write-Error-Custom "Backup failed!"
    exit 1
}
