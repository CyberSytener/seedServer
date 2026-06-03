# Secret Management & Security

**Critical security fix: Removing secrets from repository and implementing secure practices**

## 🚨 CRITICAL: Immediate Actions Required

### 1. Exposed Secrets Found

**The following secrets were found in `.env` and must be rotated IMMEDIATELY:**

```
SEED_ADMIN_KEY=<redacted-test-admin-key>     ⚠️ EXPOSED - ROTATE NOW
SEED_ADMIN_API_KEY=<redacted-admin-api-key>  ⚠️ EXPOSED - ROTATE NOW
GEMINI_API_KEY=<redacted-gemini-api-key>     ⚠️ EXPOSED - ROTATE NOW
```

### 2. Immediate Steps

```bash
# 1. Rotate all exposed keys
# - Generate new admin keys (see instructions below)
# - Revoke and regenerate Gemini API key at https://makersuite.google.com/app/apikey

# 2. Update your local .env with new keys
cp .env.example .env
# Edit .env and add new secure keys

# 3. Verify .env is not tracked by git
git status .env
# Should show: "Untracked files" or nothing

# 4. Ensure .gitignore contains .env
cat .gitignore | grep "^\.env$"
# Should output: .env
```

---

## ✅ Security Improvements Implemented

### 1. Created `.env.example` Template

**Before**: `.env` file with real secrets in repository  
**After**: `.env.example` template with no secrets, comprehensive documentation

**Features**:
- ✅ No real secrets included
- ✅ Detailed instructions for each variable
- ✅ Security warnings for dangerous settings
- ✅ Production deployment checklist
- ✅ Key generation commands included

### 2. Created `.gitignore`

**Purpose**: Prevent accidental secret commits

**Protected Files**:
```
.env
.env.local
.env.*.local
*.pem
*.key
*.crt
*.db
*.sqlite
```

### 3. Secured `.env` File

**Actions Taken**:
- ✅ `.env` is in `.gitignore` (never committed)
- ✅ `.env.example` has no secrets (safe to commit)
- ✅ Documentation warns against committing secrets

---

## 🔐 Generating Secure Secrets

### Admin Keys

```bash
# Generate SEED_ADMIN_KEY (32-character random string)
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Example output: xK9mP2nQ4rT6wY8zA1bC3dE5fG7hI9jL

# Generate SEED_ADMIN_API_KEY (with seed_ prefix)
python -c "import secrets; print('seed_' + secrets.token_urlsafe(32))"
# Example output: seed_xK9mP2nQ4rT6wY8zA1bC3dE5fG7hI9jL
```

### API Key Pepper

```bash
# Generate SEED_API_KEY_PEPPER (used for hashing)
python -c "import secrets; print(secrets.token_urlsafe(64))"
# Example output: yL0nM2oP4qR6sT8uV1wX3zY5aB7cD9eF...
```

**⚠️ WARNING**: Never change `SEED_API_KEY_PEPPER` after deployment - it will invalidate all existing API keys!

---

## 📋 Environment Setup Guide

### Local Development

```bash
# 1. Copy template
cp .env.example .env

# 2. Generate admin keys
ADMIN_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
ADMIN_API_KEY=$(python -c "import secrets; print('seed_' + secrets.token_urlsafe(32))")
API_KEY_PEPPER=$(python -c "import secrets; print(secrets.token_urlsafe(64))")

# 3. Update .env (manual or script)
echo "SEED_ADMIN_KEY=$ADMIN_KEY" >> .env
echo "SEED_ADMIN_API_KEY=$ADMIN_API_KEY" >> .env
echo "SEED_API_KEY_PEPPER=$API_KEY_PEPPER" >> .env

# 4. Add LLM API keys (if needed)
# Edit .env and add:
# OPENAI_API_KEY=sk-...
# GEMINI_API_KEY=AIza...

# 5. Enable dev-friendly settings
echo "SEED_ENABLE_LEGACY_X_USER_ID=1" >> .env
echo "SEED_DEV_CORS=1" >> .env
echo "SEED_DEFAULT_PROVIDER_FAST=stub" >> .env
echo "SEED_DEFAULT_PROVIDER_BATCH=stub" >> .env
```

### Production Deployment

```bash
# 1. Use secrets management system
# - AWS Secrets Manager
# - HashiCorp Vault
# - Google Secret Manager
# - Azure Key Vault

# 2. Set environment variables directly (don't use .env file)
export SEED_ADMIN_KEY="production_secure_key_here"
export SEED_ADMIN_API_KEY="seed_production_api_key_here"
export SEED_API_KEY_PEPPER="production_pepper_64_chars_long"

# 3. Configure LLM providers
export OPENAI_API_KEY="sk-prod-..."
export GEMINI_API_KEY="AIza..."

# 4. Secure production settings
export SEED_ENABLE_LEGACY_X_USER_ID=0
export SEED_DEV_CORS=0
export SEED_CORS_ORIGINS="https://yourdomain.com"
export SEED_DEFAULT_PROVIDER_FAST="openai"
export SEED_DEFAULT_PROVIDER_BATCH="openai"
```

---

## 🛡️ Security Best Practices

### Secret Storage

✅ **DO**:
- Use environment variables
- Use secrets management systems
- Rotate keys regularly
- Use different keys per environment
- Keep `.env` in `.gitignore`
- Use `.env.example` template

❌ **DON'T**:
- Commit `.env` to git
- Share keys via email/Slack
- Use same keys for dev/prod
- Hardcode secrets in code
- Store secrets in Docker images
- Log secret values

### Key Rotation

```bash
# 1. Generate new keys
NEW_ADMIN_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

# 2. Update production environment
# (use your deployment tool)

# 3. Verify new key works
curl -H "X-Admin-Key: $NEW_ADMIN_KEY" https://api.yourdomain.com/health

# 4. Revoke old key
# (depends on your secrets management system)

# 5. Update team
# Notify team members to update local .env
```

### API Key Management

**Gemini API Key**:
```bash
# 1. Go to: https://makersuite.google.com/app/apikey
# 2. Click "Create API Key"
# 3. Copy key immediately (can't view again)
# 4. Add to .env: GEMINI_API_KEY=AIza...
# 5. To rotate: Delete old key, create new key
```

**OpenAI API Key**:
```bash
# 1. Go to: https://platform.openai.com/api-keys
# 2. Click "Create new secret key"
# 3. Name it (e.g., "seed-server-prod")
# 4. Copy key immediately (can't view again)
# 5. Add to .env: OPENAI_API_KEY=sk-...
# 6. To rotate: Revoke old key, create new key
```

---

## 🔍 Verification Checklist

Run this checklist before deploying:

```bash
# 1. Verify .env is not tracked
git ls-files .env
# Should output nothing

# 2. Verify .gitignore has .env
grep "^\.env$" .gitignore
# Should output: .env

# 3. Check for secrets in git history
git log --all --full-history --source --pickaxe-all -S "GEMINI_API_KEY"
# Should find no commits

# 4. Verify .env.example has no secrets
grep -i "api.*key.*=" .env.example | grep -v "^#" | grep -v "=$"
# Should output nothing (all keys should be empty)

# 5. Test with stub provider (no real keys)
SEED_DEFAULT_PROVIDER_FAST=stub python -c "from app.settings import get_settings; print(get_settings().default_provider_fast)"
# Should output: stub
```

---

## 🚨 If Secrets Were Committed to Git

### Immediate Actions

```bash
# 1. Rotate ALL exposed keys immediately
# - Admin keys
# - API keys
# - Pepper keys

# 2. Check git history
git log --all --full-history --source --pickaxe-all -S "GEMINI_API_KEY"

# 3. If found, contact provider to revoke keys
# - Gemini: https://makersuite.google.com/app/apikey
# - OpenAI: https://platform.openai.com/api-keys

# 4. Remove from git history (destructive!)
# WARNING: This rewrites history, coordinate with team
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch .env' \
  --prune-empty --tag-name-filter cat -- --all

# 5. Force push (coordinate with team!)
git push origin --force --all
git push origin --force --tags

# 6. Have all team members re-clone
# Old clones will still have secrets in history
```

### Prevention

```bash
# 1. Add pre-commit hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
if git diff --cached --name-only | grep -q "^\.env$"; then
    echo "ERROR: Attempting to commit .env file!"
    echo "This file contains secrets and should never be committed."
    exit 1
fi
EOF
chmod +x .git/hooks/pre-commit

# 2. Use git-secrets
# https://github.com/awslabs/git-secrets
brew install git-secrets  # macOS
# or: apt-get install git-secrets  # Ubuntu
git secrets --install
git secrets --register-aws
```

---

## 📊 Current Status

### Before ❌

```
❌ .env file contained real secrets
❌ Admin keys in plain text
❌ Gemini API key exposed
❌ No .gitignore for secrets
❌ No .env.example template
❌ No security documentation
```

### After ✅

```
✅ .env.example template created (no secrets)
✅ .gitignore prevents secret commits
✅ Comprehensive security documentation
✅ Key generation instructions
✅ Rotation procedures documented
✅ Production checklist provided
```

---

## 🔄 Key Rotation Schedule

### Recommended Rotation Frequency

| Secret Type | Frequency | Reason |
|-------------|-----------|--------|
| Admin keys | Every 90 days | Limit exposure window |
| API keys (LLM) | Every 180 days | Provider best practices |
| API key pepper | Never* | Invalidates all user keys |

*Only change pepper during major version upgrades with migration plan

### Rotation Process

```bash
# 1. Generate new keys
./scripts/generate_keys.sh

# 2. Update secrets management
# (AWS/Vault/etc)

# 3. Deploy to staging
# Verify everything works

# 4. Deploy to production
# Monitor for issues

# 5. Revoke old keys after 24h
# Grace period for rollback
```

---

## 🛠️ Helper Scripts

### Generate All Keys

```bash
#!/bin/bash
# scripts/generate_keys.sh

echo "Generating secure keys..."
echo ""

echo "SEED_ADMIN_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")"
echo "SEED_ADMIN_API_KEY=seed_$(python -c "import secrets; print(secrets.token_urlsafe(32))")"
echo "SEED_API_KEY_PEPPER=$(python -c "import secrets; print(secrets.token_urlsafe(64))")"
echo ""
echo "⚠️  Save these securely! They cannot be recovered."
```

### Check for Secrets

```bash
#!/bin/bash
# scripts/check_secrets.sh

echo "Checking for committed secrets..."

# Check if .env is tracked
if git ls-files .env | grep -q .env; then
    echo "❌ ERROR: .env is tracked by git!"
    exit 1
fi

# Check for API keys in code
if git grep -i "GEMINI_API_KEY.*=.*AIza" >/dev/null 2>&1; then
    echo "❌ ERROR: Gemini API key found in code!"
    exit 1
fi

if git grep -i "OPENAI_API_KEY.*=.*sk-" >/dev/null 2>&1; then
    echo "❌ ERROR: OpenAI API key found in code!"
    exit 1
fi

echo "✅ No secrets found in tracked files"
```

---

## 📚 References

- [OWASP Secret Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [12-Factor App: Config](https://12factor.net/config)
- [AWS Secrets Manager](https://aws.amazon.com/secrets-manager/)
- [HashiCorp Vault](https://www.vaultproject.io/)
- [git-secrets](https://github.com/awslabs/git-secrets)

---

## 🆘 Emergency Contacts

If you believe secrets have been compromised:

1. **Rotate all keys immediately**
2. **Check for unauthorized usage** (API dashboards)
3. **Review logs** for suspicious activity
4. **Notify team** of the breach
5. **Document the incident**

---

**Last Updated**: 2026-01-11  
**Status**: ✅ Security improvements implemented  
**Action Required**: ⚠️ Rotate exposed keys immediately
