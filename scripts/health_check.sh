#!/usr/bin/env bash
set -euo pipefail

BASE_URL="http://127.0.0.1:8000"
API_TOKEN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --api-token)
      API_TOKEN="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: $0 [--base-url URL] [--api-token TOKEN]"
      exit 1
      ;;
  esac
done

echo "Health check target: $BASE_URL"

tmp_health="$(mktemp)"
health_status="$(curl -sS -o "$tmp_health" -w "%{http_code}" "$BASE_URL/health")"
if [[ "$health_status" != "200" ]]; then
  echo "FAIL /health returned HTTP $health_status"
  rm -f "$tmp_health"
  exit 1
fi

if ! grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' "$tmp_health"; then
  echo "FAIL /health did not contain ok=true"
  rm -f "$tmp_health"
  exit 1
fi
rm -f "$tmp_health"
echo "PASS /health -> ok=true"

me_without_auth_status="$(curl -sS -o /dev/null -w "%{http_code}" "$BASE_URL/v1/me")"
if [[ "$me_without_auth_status" != "401" ]]; then
  echo "FAIL expected /v1/me without auth to return 401, got $me_without_auth_status"
  exit 1
fi
echo "PASS /v1/me without auth -> 401"

if [[ -n "$API_TOKEN" ]]; then
  me_with_auth_status="$(curl -sS -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $API_TOKEN" "$BASE_URL/v1/me")"
  if [[ "$me_with_auth_status" != "200" ]]; then
    echo "FAIL expected /v1/me with auth token to return 200, got $me_with_auth_status"
    exit 1
  fi
  echo "PASS /v1/me with auth token -> 200"
fi

echo "Public health checks completed."
