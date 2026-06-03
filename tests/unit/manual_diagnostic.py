"""
Test script for diagnostic items endpoint.

Usage:
    python test_diagnostic.py
"""
import json
import requests
import os
from pathlib import Path

# Load API key from .env
env_file = Path(__file__).parent / ".env"
api_key = None

if env_file.exists():
    for line in env_file.read_text().split('\n'):
        if line.startswith('SEED_ADMIN_API_KEY='):
            api_key = line.split('=', 1)[1].strip()
            break

if not api_key:
    print("❌ No API key found in .env")
    exit(1)

# Test data
test_request = {
    "nativeLang": "English",
    "targetLang": "French",
    "blueprint": [
        {
            "skill": "grammar",
            "subskill": "verb_conjugation",
            "topic": "present_tense",
            "difficulty": 2.0,
            "taskType": "mcq",
            "cefrBand": "A2"
        },
        {
            "skill": "vocabulary",
            "subskill": "common_words",
            "topic": "greetings",
            "difficulty": 1.0,
            "taskType": "translate",
            "cefrBand": "A1"
        }
    ],
    "personaId": "classic_tutor"
}

# Make request
url = "http://localhost:8000/v1/diagnostics/generate"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

print("🧪 Testing diagnostic items endpoint...")
print(f"   URL: {url}")
print(f"   Generating {len(test_request['blueprint'])} items")

try:
    response = requests.post(url, headers=headers, json=test_request, timeout=60)
    
    if response.status_code == 200:
        data = response.json()
        items = data.get("diagnosticSet", {}).get("items", [])
        
        print(f"\n✅ SUCCESS! Generated {len(items)} diagnostic items")
        print(f"   Persona used: {data.get('personaIdUsed')}")
        
        # Show first item details
        if items:
            item = items[0]
            print(f"\n📝 Sample item:")
            print(f"   ID: {item.get('id')}")
            print(f"   Type: {item.get('type')}")
            print(f"   Prompt: {item.get('prompt')[:60]}...")
            
            if item.get('choices'):
                print(f"   Choices: {len(item.get('choices'))} options")
            
            if item.get('answer'):
                print(f"   Accepted answers: {len(item['answer'].get('accepted', []))}")
            
            if item.get('tags'):
                tags = item['tags']
                print(f"   Tags: {tags.get('skill')} | {tags.get('cefrBand')} | difficulty={tags.get('difficulty')}")
        
        # Save full response
        output_file = Path(__file__).parent / "diagnostic_test_response.json"
        output_file.write_text(json.dumps(data, indent=2))
        print(f"\n💾 Full response saved to: {output_file.name}")
        
    else:
        print(f"\n❌ ERROR {response.status_code}")
        print(f"   {response.text}")
        
except requests.exceptions.Timeout:
    print("\n⏱️  Request timed out (>60s)")
except Exception as e:
    print(f"\n❌ Exception: {e}")
