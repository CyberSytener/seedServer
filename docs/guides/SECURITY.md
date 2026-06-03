# Security Policy

## Supported Versions

We release patches for security vulnerabilities. Which versions are eligible for receiving such patches depends on the CVSS v3.0 Rating:

| Version | Supported          |
| ------- | ------------------ |
| 5.x.x   | :white_check_mark: |
| < 5.0   | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to: **security@example.com** (replace with actual email)

You should receive a response within 48 hours. If for some reason you do not, please follow up via email to ensure we received your original message.

Please include the following information:

- Type of issue (e.g. buffer overflow, SQL injection, cross-site scripting, etc.)
- Full paths of source file(s) related to the manifestation of the issue
- The location of the affected source code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce the issue
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit it

This information will help us triage your report more quickly.

## Preferred Languages

We prefer all communications to be in English.

## Security Update Policy

When we receive a security bug report, we will:

1. **Acknowledge receipt** within 48 hours
2. **Assess severity** using CVSS v3.0 scoring
3. **Develop a fix** with appropriate priority:
   - Critical (CVSS 9.0-10.0): Within 24 hours
   - High (CVSS 7.0-8.9): Within 7 days
   - Medium (CVSS 4.0-6.9): Within 30 days
   - Low (CVSS 0.1-3.9): Next regular release
4. **Release patch** with security advisory
5. **Credit reporter** (if desired) in release notes

## Security Measures

### Automated Security Scanning

We use the following automated security tools:

#### 1. **Dependency Scanning**
- **Tools**: Safety, pip-audit, Dependabot
- **Frequency**: Weekly + on every PR
- **Action**: Automatic PRs for vulnerable dependencies

#### 2. **Secret Scanning**
- **Tools**: TruffleHog, GitHub Secret Scanning
- **Frequency**: On every commit
- **Action**: Immediate alert + PR block

#### 3. **Static Application Security Testing (SAST)**
- **Tools**: Bandit, CodeQL
- **Frequency**: On every PR
- **Action**: Block PR if critical issues found

#### 4. **Container Scanning**
- **Tools**: Trivy
- **Frequency**: On Docker builds
- **Action**: Alert on HIGH/CRITICAL vulnerabilities

#### 5. **Code Coverage**
- **Tool**: pytest-cov
- **Threshold**: 70% minimum
- **Action**: Block PR if coverage drops

### Manual Security Reviews

Critical changes require manual security review:

- Authentication/Authorization changes
- Cryptographic implementations
- Database query modifications
- API endpoint additions
- LLM prompt injections
- Input validation changes

## Known Security Measures

### Input Validation
- All user inputs are validated and sanitized
- LLM outputs are validated against strict schemas (see `LLM_TRUST_BOUNDARY.md`)
- SQL injection prevention via parameterized queries
- XSS prevention via output encoding

### Authentication & Authorization
- API key-based authentication
- Role-based access control (RBAC)
- Rate limiting on all endpoints
- Session management with secure tokens

### Data Protection
- Passwords hashed with bcrypt
- API keys stored securely
- Sensitive data encrypted at rest
- TLS 1.2+ enforced for all connections

### LLM Security
- Prompt injection prevention
- Output validation with schema enforcement
- Timeout limits on LLM requests
- Token usage limits

## Security Best Practices for Contributors

### Code Security
1. Never commit secrets, API keys, or passwords
2. Use parameterized queries for database access
3. Validate all user inputs
4. Sanitize all outputs
5. Follow principle of least privilege
6. Use secure random number generation

### Dependency Management
1. Keep dependencies up to date
2. Review dependency changes in PRs
3. Use lock files (`requirements.txt` with pinned versions)
4. Avoid dependencies with known vulnerabilities
5. Minimize dependency footprint

### Docker Security
1. Use official base images
2. Run as non-root user
3. Scan images for vulnerabilities
4. Keep base images updated
5. Minimize image layers

### API Security
1. Always require authentication
2. Implement rate limiting
3. Validate request sizes
4. Use CORS properly
5. Return appropriate error messages (no stack traces to users)

## Security Checklist for PRs

Before submitting a PR, ensure:

- [ ] No hardcoded secrets or API keys
- [ ] All inputs are validated
- [ ] All outputs are sanitized
- [ ] Tests cover security-critical code
- [ ] No new high/critical vulnerabilities introduced
- [ ] Documentation updated for security-relevant changes
- [ ] Code coverage meets threshold (70%)

## Security Training

All contributors are encouraged to:

1. Review [OWASP Top 10](https://owasp.org/www-project-top-ten/)
2. Review [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
3. Review [OWASP LLM Top 10](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
4. Complete secure coding training
5. Stay updated on security advisories

## Contact

For security concerns, contact:
- Email: security@example.com
- Security Team: @security-team (GitHub)

## Hall of Fame

We recognize security researchers who responsibly disclose vulnerabilities:

<!-- Security researchers will be listed here -->

---

**Last Updated**: January 11, 2026  
**Policy Version**: 1.0
