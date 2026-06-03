#!/usr/bin/env bash

# Database Backup Script for Seed Server
# Performs backup of SQLite database with rotation and compression

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DB_PATH="${DATABASE_URL:-sqlite:///$PROJECT_ROOT/data/seed_server.db}"
DB_PATH="${DB_PATH#sqlite:///}"  # Remove sqlite:/// prefix
BACKUP_DIR="$PROJECT_ROOT/data/backups"
MAX_BACKUPS=30  # Keep last 30 backups
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="seed_server_${TIMESTAMP}.db"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Check if database exists
if [ ! -f "$DB_PATH" ]; then
    log_error "Database not found at: $DB_PATH"
    exit 1
fi

log_info "Starting database backup..."
log_info "Source: $DB_PATH"
log_info "Destination: $BACKUP_DIR/$BACKUP_NAME"

# Perform SQLite backup using .backup command
sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/$BACKUP_NAME'"

if [ $? -eq 0 ]; then
    log_info "Backup created successfully: $BACKUP_NAME"
    
    # Get backup size
    BACKUP_SIZE=$(du -h "$BACKUP_DIR/$BACKUP_NAME" | cut -f1)
    log_info "Backup size: $BACKUP_SIZE"
    
    # Compress backup
    log_info "Compressing backup..."
    gzip "$BACKUP_DIR/$BACKUP_NAME"
    COMPRESSED_SIZE=$(du -h "$BACKUP_DIR/${BACKUP_NAME}.gz" | cut -f1)
    log_info "Compressed size: $COMPRESSED_SIZE"
    
    # Cleanup old backups
    log_info "Cleaning up old backups (keeping last $MAX_BACKUPS)..."
    ls -t "$BACKUP_DIR"/seed_server_*.db.gz 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)) | xargs -r rm
    
    REMAINING_BACKUPS=$(ls -1 "$BACKUP_DIR"/seed_server_*.db.gz 2>/dev/null | wc -l)
    log_info "Backup complete. Total backups: $REMAINING_BACKUPS"
    
    # Verify backup integrity
    log_info "Verifying backup integrity..."
    gunzip -c "$BACKUP_DIR/${BACKUP_NAME}.gz" > "/tmp/${BACKUP_NAME}"
    sqlite3 "/tmp/${BACKUP_NAME}" "PRAGMA integrity_check;" > /tmp/integrity_result.txt
    
    if grep -q "ok" /tmp/integrity_result.txt; then
        log_info "Backup integrity verified: OK"
    else
        log_error "Backup integrity check failed!"
        cat /tmp/integrity_result.txt
        rm "/tmp/${BACKUP_NAME}"
        exit 1
    fi
    
    rm "/tmp/${BACKUP_NAME}"
    rm /tmp/integrity_result.txt
    
else
    log_error "Backup failed!"
    exit 1
fi

exit 0
