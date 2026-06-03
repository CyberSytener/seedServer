#!/bin/bash
# Seed LocalStack S3 bucket for local development

set -e

echo "📦 Setting up LocalStack S3 bucket..."

# Wait for LocalStack to be ready
echo "⏳ Waiting for LocalStack to be ready..."
max_attempts=30
attempt=0

while [ $attempt -lt $max_attempts ]; do
    if curl -s http://localstack:4566/_localstack/health | grep -q '"services"'; then
        echo "✅ LocalStack is ready"
        break
    fi
    attempt=$((attempt + 1))
    if [ $attempt -eq $max_attempts ]; then
        echo "❌ LocalStack failed to start"
        exit 1
    fi
    sleep 1
done

# Create S3 bucket
echo "🪣 Creating S3 bucket: seed-photos-dev"
aws s3 mb s3://seed-photos-dev \
    --endpoint-url http://localstack:4566 \
    --region us-east-1 || echo "Bucket may already exist"

# Set bucket policies
echo "🔐 Setting bucket CORS and lifecycle..."
cat > /tmp/cors.json << 'EOF'
{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["x-amz-server-side-encryption", "x-amz-request-id"],
      "MaxAgeSeconds": 3000
    }
  ]
}
EOF

aws s3api put-bucket-cors \
    --bucket seed-photos-dev \
    --cors-configuration file:///tmp/cors.json \
    --endpoint-url http://localstack:4566 || echo "CORS may already be set"

# Lifecycle policy (30-day cleanup)
cat > /tmp/lifecycle.json << 'EOF'
{
  "Rules": [
    {
      "Id": "DeleteOldJobs",
      "Status": "Enabled",
      "Prefix": "jobs/",
      "Expiration": {
        "Days": 30
      }
    }
  ]
}
EOF

aws s3api put-bucket-lifecycle-configuration \
    --bucket seed-photos-dev \
    --lifecycle-configuration file:///tmp/lifecycle.json \
    --endpoint-url http://localstack:4566 || echo "Lifecycle may already be set"

echo "✅ S3 bucket setup completed"
