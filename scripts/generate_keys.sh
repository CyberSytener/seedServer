#!/bin/bash
#
# Generate secure random keys for SEED server
#
# Usage: ./scripts/generate_keys.sh
#

set -e

echo "=================================================="
echo "SEED Server - Secure Key Generation"
echo "=================================================="
echo ""
echo "⚠️  SECURITY WARNING:"
echo "   - Save these keys securely"
echo "   - Never commit them to version control"
echo "   - Use different keys for dev/staging/prod"
echo ""
echo "Generating keys..."
echo ""

# Generate admin key
ADMIN_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
echo "SEED_ADMIN_KEY=$ADMIN_KEY"

# Generate admin API key
ADMIN_API_KEY=$(python -c "import secrets; print('seed_' + secrets.token_urlsafe(32))")
echo "SEED_ADMIN_API_KEY=$ADMIN_API_KEY"

# Generate API key pepper
API_KEY_PEPPER=$(python -c "import secrets; print(secrets.token_urlsafe(64))")
echo "SEED_API_KEY_PEPPER=$API_KEY_PEPPER"

echo ""
echo "=================================================="
echo "✓ Keys generated successfully"
echo "=================================================="
echo ""
echo "Next steps:"
echo "1. Copy these values to your .env file"
echo "2. Keep .env file secure and never commit it"
echo "3. For production, use a secrets management system"
echo ""
echo "⚠️  WARNING: Changing SEED_API_KEY_PEPPER will"
echo "   invalidate all existing user API keys!"
echo ""
