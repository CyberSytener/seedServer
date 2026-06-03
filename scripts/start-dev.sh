#!/bin/bash
# Start local development environment with Docker Compose

set -e

echo "🚀 Starting Seed Photo Editing local development environment..."

# Check if Docker is running
if ! docker ps > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Change to project directory
cd "$PROJECT_DIR"

# Create .env if not exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cat > .env << 'EOF'
# Database
POSTGRES_USER=seed_dev
POSTGRES_PASSWORD=seed_dev_password
POSTGRES_DB=seed_photos
DATABASE_URL=postgresql://seed_dev:seed_dev_password@postgres:5432/seed_photos

# Redis
REDIS_URL=redis://redis:6379/0

# AWS S3 (LocalStack)
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
AWS_REGION=us-east-1
S3_ENDPOINT_URL=http://localstack:4566
S3_BUCKET_NAME=seed-photos-dev

# OpenAI
OPENAI_API_KEY=sk-test-placeholder

# Photo Editing
PHOTO_MAX_FILE_SIZE_MB=20
PHOTO_RETENTION_DAYS=30

# Billing
PHOTO_REQUIRE_PAYMENT=false
PHOTO_WATERMARK_UNPAID=true
EOF
    echo "✅ .env file created"
fi

# Start services
echo "🐳 Starting Docker Compose services..."
docker-compose -f docker-compose-dev.yml up -d

# Wait for database
echo "⏳ Waiting for database to be ready..."
max_attempts=30
attempt=0

while [ $attempt -lt $max_attempts ]; do
    if docker-compose -f docker-compose-dev.yml exec -T postgres pg_isready -U seed_dev > /dev/null 2>&1; then
        echo "✅ Database is ready"
        break
    fi
    attempt=$((attempt + 1))
    if [ $attempt -eq $max_attempts ]; then
        echo "⚠️  Database took too long, continuing anyway..."
    fi
    sleep 1
done

# Run migrations
echo "📦 Running database migrations..."
docker-compose -f docker-compose-dev.yml exec -T api alembic upgrade head

# Seed S3 bucket
echo "🪣 Seeding S3 bucket..."
docker-compose -f docker-compose-dev.yml exec -T api bash scripts/seed-s3-bucket.sh

echo ""
echo "✅ Development environment is ready!"
echo ""
echo "📍 Services available at:"
echo "   🌐 API: http://localhost:8000"
echo "   📊 Swagger: http://localhost:8000/docs"
echo "   🗄️  Adminer: http://localhost:8080"
echo "   🔴 Redis Commander: http://localhost:8081"
echo ""
echo "💡 Useful commands:"
echo "   View logs: docker-compose -f docker-compose-dev.yml logs -f [service]"
echo "   Stop: docker-compose -f docker-compose-dev.yml down"
echo "   Stop with cleanup: docker-compose -f docker-compose-dev.yml down -v"
echo ""
