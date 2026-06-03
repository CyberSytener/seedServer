# Secret Management - Quick Reference

**Fast guide to securing your SEED server secrets**

---

## 🚨 CRITICAL: Exposed Keys Found

The following keys in `.env` must be rotated **immediately**:

```
❌ SEED_ADMIN_KEY=<redacted-test-admin-key>
❌ SEED_ADMIN_API_KEY=<redacted-admin-api-key>
❌ GEMINI_API_KEY=<redacted-gemini-api-key>
```

---

## ⚡ Quick Fix (5 minutes)

### 1. Generate New Keys

```bash
# Windows
powershell -File scripts/generate_keys.ps1

# Linux/Mac
./scripts/generate_keys.sh
```

**Copy the output** - you'll need it in step 3.

### 2. Revoke Gemini API Key

1. Go to: https://makersuite.google.com/app/apikey
2. Delete the exposed old key
3. Click "Create API Key"
4. Copy new key

### 3. Update `.env`

```bash
# Edit .env file
notepad .env   # Windows
nano .env      # Linux/Mac

# Replace with new values from step 1 & 2:
SEED_ADMIN_KEY=<new_key>
SEED_ADMIN_API_KEY=<new_api_key>
SEED_API_KEY_PEPPER=<new_pepper>
GEMINI_API_KEY=<new_gemini_key>
```

### 4. Verify

```bash
python verify_secret_management.py
# Should show: 6/6 checks passed
```

---

## 📋 Files Created

| File | Purpose |
|------|---------|
| `.gitignore` | Prevents committing secrets |
| `.env.example` | Safe template (no real secrets) |
| `SECRET_MANAGEMENT.md` | Full documentation |
| `scripts/generate_keys.ps1` | Generate secure keys |
| `verify_secret_management.py` | Check security |

---

## ✅ Security Checklist

Before deploying to production:

- [ ] Rotate all exposed keys
- [ ] Set `SEED_ENABLE_LEGACY_X_USER_ID=0`
- [ ] Set `SEED_DEV_CORS=0`
- [ ] Use real LLM provider (not stub)
- [ ] Verify `.env` not in git
- [ ] Document key rotation schedule

---

## 🔒 Best Practices

### ✅ DO
- Use strong random keys
- Keep `.env` local only
- Rotate keys every 90 days
- Use secrets manager in production

### ❌ DON'T
- Commit `.env` to git
- Share keys via email/Slack
- Use test keys in production
- Hardcode secrets in code

---

## 🛡️ Production Setup

Don't use `.env` in production! Use environment variables:

```bash
# Set via environment
export SEED_ADMIN_KEY="production_key_here"
export SEED_API_KEY_PEPPER="production_pepper_here"
export GEMINI_API_KEY="AIza..."

# Or use secrets management
# - AWS Secrets Manager
# - HashiCorp Vault
# - Google Secret Manager
```

---

## 🆘 Emergency: Secrets in Git History

```bash
# 1. Rotate ALL keys immediately
# 2. Revoke API keys at provider
# 3. Check git history:
git log --all -S "GEMINI_API_KEY"

# 4. If found, remove from history:
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch .env' \
  --prune-empty -- --all

# 5. Force push (coordinate with team!)
git push origin --force --all
```

---

## 📚 Full Documentation

- **Complete Guide**: [SECRET_MANAGEMENT.md](SECRET_MANAGEMENT.md)
- **Setup Template**: [.env.example](.env.example)
- **Implementation Report**: [SECRET_MANAGEMENT_COMPLETE.md](SECRET_MANAGEMENT_COMPLETE.md)

---

## ⚡ TL;DR

1. Run: `powershell -File scripts/generate_keys.ps1`
2. Revoke old Gemini key, generate new one
3. Update `.env` with new keys
4. Run: `python verify_secret_management.py`
5. Never commit `.env` to git

**Status**: Infrastructure complete, keys need rotation  
**Priority**: HIGH  
**Time**: 5 minutes
