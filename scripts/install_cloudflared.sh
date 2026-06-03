#!/usr/bin/env bash
set -euo pipefail

echo "Checking for cloudflared..."
if command -v cloudflared >/dev/null 2>&1; then
  cloudflared --version
  echo "cloudflared is already installed."
  exit 0
fi

if command -v brew >/dev/null 2>&1; then
  echo "Installing cloudflared with Homebrew..."
  brew install cloudflared
elif command -v apt-get >/dev/null 2>&1; then
  echo "Installing cloudflared with apt..."
  sudo mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y cloudflared
elif command -v dnf >/dev/null 2>&1; then
  echo "Installing cloudflared with dnf..."
  sudo dnf install -y cloudflared
elif command -v yum >/dev/null 2>&1; then
  echo "Installing cloudflared with yum..."
  sudo yum install -y cloudflared
else
  echo "No supported package manager found. Install cloudflared manually from:"
  echo "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
  exit 1
fi

cloudflared --version
echo "cloudflared installation completed."
echo "Next step: run 'cloudflared tunnel login' and follow PUBLIC_DEPLOYMENT_GUIDE.md."
