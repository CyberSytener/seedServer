"""
Script to generate OpenAPI spec from FastAPI application
"""
import json
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import create_app

# Create app instance
app = create_app()

# Get OpenAPI schema
openapi_schema = app.openapi()

# Save to file
output_file = Path(__file__).parent.parent / "docs" / "openapi.json"
output_file.parent.mkdir(parents=True, exist_ok=True)

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(openapi_schema, f, indent=2, ensure_ascii=False)

print(f"✅ OpenAPI spec saved to: {output_file}")
print(f"📊 Endpoints: {len([p for p in openapi_schema.get('paths', {}).values()])}")
print(f"📋 Schemas: {len(openapi_schema.get('components', {}).get('schemas', {}))}")
