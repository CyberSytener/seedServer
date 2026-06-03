# CI/CD Security - Quick Reference

## 🛡️ Automated Security Checks

All PRs automatically run:
- ✅ **Dependency vulnerability scanning** (Safety, pip-audit)
- ✅ **Secret detection** (TruffleHog)
- ✅ **Security linting** (Bandit)
- ✅ **Code coverage gating** (70% minimum)
- ✅ **License compliance** (no GPL/AGPL)
- ✅ **Container scanning** (Trivy)
- ✅ **SAST** (CodeQL)

## 🚀 Quick Start

### Local Development Setup
```bash
# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Install dev dependencies
pip install -r requirements-dev.txt

# Run all checks locally
pre-commit run --all-files
```

### Run Security Scans
```bash
# Dependency check
safety check
pip-audit

# Security linting
bandit -r app/ -ll

# Coverage check
pytest --cov=app --cov-fail-under=70

# Format code
black app/
isort app/
```

## 📊 Security Gates

Your PR will be **blocked** if:
- ❌ HIGH/CRITICAL vulnerabilities in dependencies
- ❌ Secrets detected
- ❌ Security issues found (Bandit)
- ❌ Code coverage < 70%
- ❌ GPL/AGPL licenses
- ❌ Tests fail

## 📁 Key Files

| File | Purpose |
|------|---------|
| [.github/workflows/security-scan.yml](.github/workflows/security-scan.yml) | Full security scanning suite |
| [.github/workflows/coverage.yml](.github/workflows/coverage.yml) | Coverage gating (70%) |
| [.github/workflows/ci.yml](.github/workflows/ci.yml) | Standard CI pipeline |
| [.pre-commit-config.yaml](.pre-commit-config.yaml) | Local pre-commit hooks |
| [SECURITY.md](SECURITY.md) | Security policy |
| [CI_SECURITY_GUIDE.md](CI_SECURITY_GUIDE.md) | Complete guide |

## 🔍 View Results

- **Security Findings**: GitHub Security tab
- **Coverage Reports**: PR comments + artifacts
- **Scan Reports**: Workflow artifacts (30-day retention)

## 📚 Documentation

- **Full Guide**: [CI_SECURITY_GUIDE.md](CI_SECURITY_GUIDE.md)
- **Summary**: [CI_SECURITY_SUMMARY.md](CI_SECURITY_SUMMARY.md)
- **Security Policy**: [SECURITY.md](SECURITY.md)

## 🆘 Support

- Security issues: security@example.com
- Questions: See [CI_SECURITY_GUIDE.md](CI_SECURITY_GUIDE.md)

---

✅ **Status**: Production Ready | **Last Updated**: January 11, 2026
