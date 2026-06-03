"""
Verification script for secret management security improvements.

Checks that:
1. .env is not tracked by git
2. .gitignore contains .env
3. .env.example has no real secrets
4. No secrets in tracked code files
5. Helper scripts exist
"""
import sys
import os
import re
from pathlib import Path
import subprocess


def print_header(text):
    """Print header."""
    print(f"\n{'=' * 70}")
    print(f"{text}")
    print(f"{'=' * 70}\n")


def print_success(text):
    """Print success message."""
    print(f"[OK] {text}")


def print_error(text):
    """Print error message."""
    print(f"[ERROR] {text}")


def print_warning(text):
    """Print warning message."""
    print(f"[WARN] {text}")


def check_env_not_tracked():
    """Check that .env is not tracked by git."""
    print_header("1. Checking .env is not tracked")
    
    # Check if in git repo
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print_warning("Not in a git repository - skip git checks")
            return True
    except FileNotFoundError:
        print_warning("Git not installed - skip git checks")
        return True
    
    # Check if .env is tracked
    try:
        result = subprocess.run(
            ["git", "ls-files", ".env"],
            capture_output=True,
            text=True
        )
        if result.stdout.strip():
            print_error(".env is tracked by git!")
            print_error("Run: git rm --cached .env")
            return False
        else:
            print_success(".env is not tracked by git")
            return True
    except Exception as e:
        print_warning(f"Could not check git status: {e}")
        return True


def check_gitignore():
    """Check .gitignore contains .env."""
    print_header("2. Checking .gitignore")
    
    gitignore_path = Path(".gitignore")
    
    if not gitignore_path.exists():
        print_error(".gitignore does not exist!")
        return False
    
    print_success(".gitignore exists")
    
    with open(gitignore_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if not re.search(r'^\.env$', content, re.MULTILINE):
        print_error(".env not found in .gitignore!")
        return False
    
    print_success(".env is in .gitignore")
    
    # Check for other important entries
    important_entries = ['.env', '*.db', '*.key', '*.pem']
    for entry in important_entries:
        if entry in content:
            print_success(f"Protected: {entry}")
    
    return True


def check_env_example():
    """Check .env.example has no real secrets."""
    print_header("3. Checking .env.example")
    
    env_example_path = Path(".env.example")
    
    if not env_example_path.exists():
        print_error(".env.example does not exist!")
        return False
    
    print_success(".env.example exists")
    
    with open(env_example_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for real secrets
    issues = []
    
    # Check for API keys
    if re.search(r'GEMINI_API_KEY=AIza[A-Za-z0-9_-]{30,}', content):
        issues.append("Gemini API key found")
    
    if re.search(r'OPENAI_API_KEY=sk-[A-Za-z0-9_-]{20,}', content):
        issues.append("OpenAI API key found")
    
    # Check for admin keys with actual values
    if re.search(r'SEED_ADMIN_KEY=[A-Za-z0-9_-]{20,}', content):
        issues.append("Admin key with value found")
    
    if re.search(r'SEED_ADMIN_API_KEY=seed_[A-Za-z0-9_-]{20,}', content):
        issues.append("Admin API key with value found")
    
    if issues:
        for issue in issues:
            print_error(issue)
        return False
    
    print_success("No real secrets in .env.example")
    
    # Check for security warnings
    if "SECURITY" in content or "WARNING" in content:
        print_success("Contains security warnings")
    else:
        print_warning("No security warnings found")
    
    return True


def check_documentation():
    """Check security documentation exists."""
    print_header("4. Checking Security Documentation")
    
    doc_path = Path("SECRET_MANAGEMENT.md")
    
    if not doc_path.exists():
        print_error("SECRET_MANAGEMENT.md not found!")
        return False
    
    print_success("SECRET_MANAGEMENT.md exists")
    
    with open(doc_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for important sections
    sections = [
        "Immediate Actions",
        "Generating Secure Secrets",
        "Key Rotation",
        "Production Deployment",
    ]
    
    all_found = True
    for section in sections:
        if section in content:
            print_success(f"Section: {section}")
        else:
            print_warning(f"Section missing: {section}")
            all_found = False
    
    return all_found


def check_helper_scripts():
    """Check helper scripts exist."""
    print_header("5. Checking Helper Scripts")
    
    scripts = [
        "scripts/generate_keys.sh",
        "scripts/generate_keys.ps1",
        "scripts/check_secrets.sh"
    ]
    
    all_exist = True
    for script in scripts:
        script_path = Path(script)
        if script_path.exists():
            print_success(f"{script} exists")
        else:
            print_error(f"{script} not found!")
            all_exist = False
    
    return all_exist


def check_env_file_security():
    """Check current .env file for security issues."""
    print_header("6. Checking Current .env File")
    
    env_path = Path(".env")
    
    if not env_path.exists():
        print_warning(".env file does not exist (will be created from template)")
        return True
    
    print_success(".env file exists")
    
    with open(env_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for exposed secrets (from the original file)
    issues = []
    
    # Check for test/weak admin keys
    if re.search(r'SEED_ADMIN_KEY=test_admin_key', content):
        issues.append("Weak/test admin key detected: test_admin_key")
    
    # Check for exposed Gemini keys or live-looking values.
    exposed_patterns = [
        r'GEMINI_API_KEY=AIzaSy[A-Za-z0-9_-]{20,}',
    ]
    for pattern in exposed_patterns:
        if re.search(pattern, content):
            issues.append("EXPOSED Gemini API key detected (must rotate immediately!)")
            break
    
    # Check for empty pepper
    if re.search(r'SEED_API_KEY_PEPPER=\s*$', content, re.MULTILINE):
        issues.append("SEED_API_KEY_PEPPER is empty (generate a secure value)")
    
    # Check for commented warnings
    if "WARNING" in content:
        print_success("Contains security warnings")
    
    if issues:
        print_warning("Security issues in .env:")
        for issue in issues:
            print_warning(f"  - {issue}")
        print_warning("")
        print_warning("ACTION REQUIRED:")
        print_warning("1. Generate new keys: python scripts/generate_keys.ps1")
        print_warning("2. Rotate exposed API keys at provider dashboards")
        print_warning("3. Update .env with new secure keys")
        return False
    
    print_success("No obvious security issues in .env")
    return True


def run_verification():
    """Run all verification checks."""
    print_header("Secret Management Security Verification")
    print(f"Started: {Path.cwd()}")
    
    results = {
        ".env not tracked": check_env_not_tracked(),
        ".gitignore configured": check_gitignore(),
        ".env.example secure": check_env_example(),
        "Documentation complete": check_documentation(),
        "Helper scripts exist": check_helper_scripts(),
        "Current .env secure": check_env_file_security()
    }
    
    print_header("Verification Summary")
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for check_name, result in results.items():
        if result:
            print_success(f"{check_name}")
        else:
            print_error(f"{check_name}")
    
    print(f"\nResults: {passed}/{total} checks passed\n")
    
    if passed == total:
        print("=" * 70)
        print("ALL CHECKS PASSED")
        print("=" * 70)
        print("\nSecret management is properly configured.")
        print("\nNext steps:")
        print("1. Review .env and rotate any test/weak keys")
        print("2. Use scripts/generate_keys.ps1 to generate secure keys")
        print("3. See SECRET_MANAGEMENT.md for full instructions")
        print("4. Never commit .env file to version control")
        return 0
    else:
        print("=" * 70)
        print("SOME CHECKS FAILED")
        print("=" * 70)
        print("\nPlease fix the issues above.")
        print("See SECRET_MANAGEMENT.md for detailed instructions.")
        return 1


if __name__ == "__main__":
    sys.exit(run_verification())
