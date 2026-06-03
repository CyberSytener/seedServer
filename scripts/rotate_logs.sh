#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="logs/public"
RETENTION_DAYS=7
MAX_FILE_SIZE_MB=50

while [[ $# -gt 0 ]]; do
  case "$1" in
    --log-dir)
      LOG_DIR="$2"
      shift 2
      ;;
    --retention-days)
      RETENTION_DAYS="$2"
      shift 2
      ;;
    --max-file-size-mb)
      MAX_FILE_SIZE_MB="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: $0 [--log-dir DIR] [--retention-days DAYS] [--max-file-size-mb MB]"
      exit 1
      ;;
  esac
done

mkdir -p "$LOG_DIR"
max_bytes=$((MAX_FILE_SIZE_MB * 1024 * 1024))
timestamp="$(date +%Y%m%d%H%M%S)"
rotated_count=0

shopt -s nullglob
for file in "$LOG_DIR"/*.log; do
  size="$(wc -c < "$file")"
  if [[ "$size" -gt "$max_bytes" ]]; then
    mv "$file" "$file.$timestamp"
    : > "$file"
    rotated_count=$((rotated_count + 1))
  fi
done
shopt -u nullglob

deleted_count="$(find "$LOG_DIR" -type f -mtime +"$RETENTION_DAYS" -print -delete | wc -l | tr -d ' ')"

echo "Log rotation complete."
echo "Rotated files: $rotated_count"
echo "Deleted old files: $deleted_count"
echo "Log directory: $LOG_DIR"
