# Generate secure random keys for SEED server
#
# Usage: .\scripts\generate_keys.ps1
#

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "SEED Server - Secure Key Generation" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "WARNING:" -ForegroundColor Yellow
Write-Host "  - Save these keys securely" -ForegroundColor Yellow
Write-Host "  - Never commit them to version control" -ForegroundColor Yellow
Write-Host "  - Use different keys for dev/staging/prod" -ForegroundColor Yellow
Write-Host ""
Write-Host "Generating keys..." -ForegroundColor Green
Write-Host ""

# Generate admin key
$ADMIN_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
Write-Host "SEED_ADMIN_KEY=$ADMIN_KEY"

# Generate admin API key
$ADMIN_API_KEY = python -c "import secrets; print('seed_' + secrets.token_urlsafe(32))"
Write-Host "SEED_ADMIN_API_KEY=$ADMIN_API_KEY"

# Generate API key pepper
$API_KEY_PEPPER = python -c "import secrets; print(secrets.token_urlsafe(64))"
Write-Host "SEED_API_KEY_PEPPER=$API_KEY_PEPPER"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Keys generated successfully" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Copy these values to your .env file"
Write-Host "2. Keep .env file secure and never commit it"
Write-Host "3. For production, use a secrets management system"
Write-Host ""
Write-Host "WARNING: Changing SEED_API_KEY_PEPPER will" -ForegroundColor Yellow
Write-Host "invalidate all existing user API keys!" -ForegroundColor Yellow
Write-Host ""
