#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="docker-compose.public.yml"
ENV_FILE=".env.public"
PROJECT_NAME="seed_public"
NO_BUILD=false
NO_TUNNEL=false

get_env_value() {
  local key="$1"
  grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' || true
}

is_truthy() {
  local v="${1:-}"
  v="$(echo "$v" | tr '[:upper:]' '[:lower:]')"
  [[ "$v" == "1" || "$v" == "true" || "$v" == "yes" || "$v" == "on" ]]
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build)
      NO_BUILD=true
      shift
      ;;
    --no-tunnel)
      NO_TUNNEL=true
      shift
      ;;
    --compose-file)
      COMPOSE_FILE="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --project-name)
      PROJECT_NAME="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: $0 [--no-build] [--no-tunnel] [--compose-file FILE] [--env-file FILE] [--project-name NAME]"
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Compose file '$COMPOSE_FILE' not found."
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file '$ENV_FILE' not found. Copy .env.public.example to .env.public and set real values first."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not in PATH."
  exit 1
fi

if ! is_truthy "$(get_env_value PUBLIC_MODE)"; then
  echo "PUBLIC_MODE must be set to 1/true in '$ENV_FILE'."
  exit 1
fi

if is_truthy "$(get_env_value SEED_TEST_AUTH_MODE)"; then
  echo "SEED_TEST_AUTH_MODE must be 0/false in public deployment."
  exit 1
fi

admin_key="$(get_env_value SEED_ADMIN_KEY)"
if [[ -z "$admin_key" || "$admin_key" == change_me* ]]; then
  echo "SEED_ADMIN_KEY must be set to a real random value in '$ENV_FILE'."
  exit 1
fi

if is_truthy "$(get_env_value SEED_ENABLE_LEGACY_X_USER_ID)"; then
  echo "SEED_ENABLE_LEGACY_X_USER_ID must be 0/false in public mode."
  exit 1
fi

compose_cmd=(docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d)
if [[ "$NO_BUILD" == "false" ]]; then
  compose_cmd+=(--build)
fi

echo "Starting public stack..."
"${compose_cmd[@]}"

bind_port="$(get_env_value PUBLIC_BIND_PORT)"
if [[ -z "$bind_port" ]]; then
  bind_port="8000"
fi

echo "Running local health checks..."
health_ok=false
for attempt in $(seq 1 10); do
  if "$SCRIPT_DIR/health_check.sh" --base-url "http://127.0.0.1:${bind_port}"; then
    health_ok=true
    break
  fi
  if [[ "$attempt" -lt 10 ]]; then
    echo "Health check attempt $attempt failed, retrying in 3 seconds..."
    sleep 3
  fi
done

if [[ "$health_ok" != "true" ]]; then
  echo "Health checks failed."
  exit 1
fi

if [[ "$NO_TUNNEL" == "true" ]]; then
  echo "Stack is running. Tunnel startup skipped (--no-tunnel)."
  exit 0
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared not found. Install it with scripts/install_cloudflared.sh."
  exit 0
fi

config_path="${HOME}/.cloudflared/config.yml"
if [[ ! -f "$config_path" ]]; then
  echo "Cloudflared config not found at '$config_path'."
  echo "Use cloudflared/config.example.yml and PUBLIC_DEPLOYMENT_GUIDE.md."
  exit 0
fi

echo "Starting cloudflared in foreground (Ctrl+C to stop tunnel)..."
cloudflared tunnel --config "$config_path" run
