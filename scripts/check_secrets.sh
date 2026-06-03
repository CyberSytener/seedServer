#!/bin/bash
#
# Check for committed secrets in git repository
#
# Usage: ./scripts/check_secrets.sh
#

set -e

echo "=================================================="
echo "SEED Server - Secret Detection"
echo "=================================================="
echo ""

HAS_ERRORS=0

# Check if .env is tracked
echo "[1/5] Checking if .env is tracked by git..."
if git ls-files .env 2>/dev/null | grep -q .env; then
    echo "❌ ERROR: .env is tracked by git!"
    echo "   Run: git rm --cached .env"
    HAS_ERRORS=1
else
    echo "✓ .env is not tracked"
fi

# Check if .gitignore exists and contains .env
echo ""
echo "[2/5] Checking .gitignore..."
if [ ! -f .gitignore ]; then
    echo "❌ ERROR: .gitignore does not exist!"
    HAS_ERRORS=1
elif ! grep -q "^\.env$" .gitignore; then
    echo "❌ ERROR: .env not in .gitignore!"
    echo "   Run: echo '.env' >> .gitignore"
    HAS_ERRORS=1
else
    echo "✓ .gitignore properly configured"
fi

# Check for Gemini API keys in code
echo ""
echo "[3/5] Checking for Gemini API keys in code..."
if git grep -i "GEMINI_API_KEY.*=.*AIza" -- '*.py' '*.js' '*.ts' 2>/dev/null | grep -v ".env.example" | grep -v "SECRET_MANAGEMENT.md" > /dev/null; then
    echo "❌ ERROR: Gemini API key found in tracked files!"
    git grep -i "GEMINI_API_KEY.*=.*AIza" -- '*.py' '*.js' '*.ts' 2>/dev/null | grep -v ".env.example" | head -5
    HAS_ERRORS=1
else
    echo "✓ No Gemini API keys in code"
fi

# Check for OpenAI API keys in code
echo ""
echo "[4/5] Checking for OpenAI API keys in code..."
if git grep -i "OPENAI_API_KEY.*=.*sk-" -- '*.py' '*.js' '*.ts' 2>/dev/null | grep -v ".env.example" | grep -v "SECRET_MANAGEMENT.md" > /dev/null; then
    echo "❌ ERROR: OpenAI API key found in tracked files!"
    git grep -i "OPENAI_API_KEY.*=.*sk-" -- '*.py' '*.js' '*.ts' 2>/dev/null | grep -v ".env.example" | head -5
    HAS_ERRORS=1
else
    echo "✓ No OpenAI API keys in code"
fi

# Check for admin keys in code
echo ""
echo "[5/5] Checking for hardcoded admin keys..."
if git grep -i "SEED_ADMIN.*=.*[a-zA-Z0-9_-]\{10,\}" -- '*.py' '*.js' '*.ts' 2>/dev/null | grep -v ".env.example" | grep -v "SECRET_MANAGEMENT.md" | grep -v "test" | grep -v "pytest" | grep -v "mock" > /dev/null; then
    echo "⚠️  WARNING: Possible admin keys found in code"
    echo "   Review these matches:"
    git grep -i "SEED_ADMIN.*=.*[a-zA-Z0-9_-]\{10,\}" -- '*.py' '*.js' '*.ts' 2>/dev/null | grep -v ".env.example" | grep -v "test" | grep -v "pytest" | head -5
else
    echo "✓ No hardcoded admin keys found"
fi

echo ""
echo "=================================================="
if [ $HAS_ERRORS -eq 0 ]; then
    echo "✓ All checks passed!"
    echo "=================================================="
    echo ""
    echo "Your repository appears secure. Remember to:"
    echo "- Never commit .env file"
    echo "- Rotate keys regularly"
    echo "- Use secrets management in production"
    exit 0
else
    echo "❌ Security issues found!"
    echo "=================================================="
    echo ""
    echo "Please fix the issues above before continuing."
    echo "See SECRET_MANAGEMENT.md for detailed instructions."
    exit 1
fi
