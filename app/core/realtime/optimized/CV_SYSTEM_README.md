"""
CV Creation System - README

РЎРёСЃС‚РµРјР° СЃРѕР·РґР°РЅРёСЏ CV СЃ AI-РіРµРЅРµСЂР°С†РёРµР№, РІРµСЂСЃРёРѕРЅРёСЂРѕРІР°РЅРёРµРј Рё СѓР»СѓС‡С€РµРЅРёРµРј С„РѕС‚РѕРіСЂР°С„РёР№.
"""

# CV Creation System

РџРѕР»РЅРѕС„СѓРЅРєС†РёРѕРЅР°Р»СЊРЅР°СЏ СЃРёСЃС‚РµРјР° РґР»СЏ СЃРѕР·РґР°РЅРёСЏ РїСЂРѕС„РµСЃСЃРёРѕРЅР°Р»СЊРЅС‹С… CV СЃ РїРѕРґРґРµСЂР¶РєРѕР№:
- AI-РіРµРЅРµСЂР°С†РёСЏ РёР· РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРіРѕ РІРІРѕРґР° (free-form text)
- РЎС‚СЂРѕРіРёРµ РєРѕРЅС‚СЂР°РєС‚С‹ РґР°РЅРЅС‹С… (Pydantic v2)
- РџРѕР»РЅРѕРµ РІРµСЂСЃРёРѕРЅРёСЂРѕРІР°РЅРёРµ СЃ РёСЃС‚РѕСЂРёРµР№ РёР·РјРµРЅРµРЅРёР№
- РћС‚РєР°С‚ Рє Р»СЋР±РѕР№ РїСЂРµРґС‹РґСѓС‰РµР№ РІРµСЂСЃРёРё
- AI-СѓР»СѓС‡С€РµРЅРёРµ С„РѕС‚РѕРіСЂР°С„РёР№ СЃ С€Р°Р±Р»РѕРЅРЅС‹РјРё РїСЂРѕРјРїС‚Р°РјРё
- Р’Р°Р»РёРґР°С†РёСЏ Рё РѕС†РµРЅРєР° РїРѕР»РЅРѕС‚С‹ CV
- Р РµРєРѕРјРµРЅРґР°С†РёРё РїРѕ СѓР»СѓС‡С€РµРЅРёСЋ

---

## рџ“‹ РћСЃРЅРѕРІРЅС‹Рµ РєРѕРјРїРѕРЅРµРЅС‚С‹

### 1. **cv_contracts.py** - РљРѕРЅС‚СЂР°РєС‚С‹ РґР°РЅРЅС‹С…

РЎС‚СЂРѕРіРёРµ Pydantic РјРѕРґРµР»Рё РґР»СЏ РІСЃРµС… С‚РёРїРѕРІ РґР°РЅРЅС‹С…:

```python
from app.core.realtime.optimized.cv_contracts import (
    CVGenerationRequest,
    CVGenerationResponse,
    CVData,
    CVVersion,
    CVConfiguration,
    PersonalInfo,
    WorkExperience,
    Education,
    PhotoEnhancementRequest
)
```

**РћСЃРЅРѕРІРЅС‹Рµ РјРѕРґРµР»Рё:**

- `CVData` - РџРѕР»РЅС‹Рµ РґР°РЅРЅС‹Рµ CV (РїРµСЂСЃРѕРЅР°Р»СЊРЅР°СЏ РёРЅС„РѕСЂРјР°С†РёСЏ, РѕРїС‹С‚, РѕР±СЂР°Р·РѕРІР°РЅРёРµ, РЅР°РІС‹РєРё)
- `CVVersion` - Р’РµСЂСЃРёСЏ CV СЃ РјРµС‚Р°РґР°РЅРЅС‹РјРё Рё РёСЃС‚РѕСЂРёРµР№
- `CVConfiguration` - РќР°СЃС‚СЂРѕР№РєРё С„РѕСЂРјР°С‚Р° Рё СЃС‚РёР»СЏ CV
- `PersonalInfo` - РљРѕРЅС‚Р°РєС‚РЅР°СЏ РёРЅС„РѕСЂРјР°С†РёСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ
- `WorkExperience` - РћРїС‹С‚ СЂР°Р±РѕС‚С‹ СЃ РґРѕСЃС‚РёР¶РµРЅРёСЏРјРё
- `Education` - РћР±СЂР°Р·РѕРІР°РЅРёРµ
- `SkillCategory` - РљР°С‚РµРіРѕСЂРёСЏ РЅР°РІС‹РєРѕРІ
- `PhotoEnhancementRequest/Response` - РЈР»СѓС‡С€РµРЅРёРµ С„РѕС‚РѕРіСЂР°С„РёР№

### 2. **cv_processor.py** - РџСЂРѕС†РµСЃСЃРѕСЂ CV

РћСЃРЅРѕРІРЅРѕР№ Р±РёР·РЅРµСЃ-Р»РѕРіРёРєР° РґР»СЏ СЂР°Р±РѕС‚С‹ СЃ CV:

```python
from app.core.realtime.optimized.cv_processor import CVProcessor

processor = CVProcessor()

# РЎРѕР·РґР°С‚СЊ CV РёР· РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРіРѕ РІРІРѕРґР°
response = await processor.generate_cv(request)

# РџСЂРёРјРµРЅРёС‚СЊ РїСЂР°РІРєРё
updated = await processor.update_cv(update_request)

# РћС‚РєР°С‚РёС‚СЊ Рє РїСЂРµРґС‹РґСѓС‰РµР№ РІРµСЂСЃРёРё
rolled_back = await processor.rollback_to_version(user_id, target_version_id)

# РџРѕР»СѓС‡РёС‚СЊ РёСЃС‚РѕСЂРёСЋ РІРµСЂСЃРёР№
versions = await processor.version_store.get_user_versions(user_id)
```

**РљР»СЋС‡РµРІС‹Рµ С„СѓРЅРєС†РёРё:**

- `generate_cv()` - Р“РµРЅРµСЂР°С†РёСЏ CV РёР· free-form С‚РµРєСЃС‚Р°
- `update_cv()` - РџСЂРёРјРµРЅРµРЅРёРµ РїСЂР°РІРѕРє СЃ СЃРѕР·РґР°РЅРёРµРј РЅРѕРІРѕР№ РІРµСЂСЃРёРё РёР»Рё РѕР±РЅРѕРІР»РµРЅРёРµРј С‚РµРєСѓС‰РµР№
- `rollback_to_version()` - РћС‚РєР°С‚ Рє Р»СЋР±РѕР№ РїСЂРµРґС‹РґСѓС‰РµР№ РІРµСЂСЃРёРё
- `get_version_diff()` - РџРѕР»СѓС‡РёС‚СЊ СЂР°Р·РЅРёС†Сѓ РјРµР¶РґСѓ РІРµСЂСЃРёСЏРјРё
- `_validate_cv_data()` - Р’Р°Р»РёРґР°С†РёСЏ Рё СЂР°СЃС‡РµС‚ completeness score

### 3. **cv_photo_enhancer.py** - РЈР»СѓС‡С€РµРЅРёРµ С„РѕС‚РѕРіСЂР°С„РёР№

AI-РѕР±СЂР°Р±РѕС‚РєР° С„РѕС‚РѕРіСЂР°С„РёР№ РґР»СЏ CV:

```python
from app.core.realtime.optimized.cv_photo_enhancer import PhotoEnhancer

enhancer = PhotoEnhancer()

# РЈР»СѓС‡С€РёС‚СЊ С„РѕС‚Рѕ
response = await enhancer.enhance_photo(request)

# РЎРѕР·РґР°С‚СЊ РІР°СЂРёР°РЅС‚С‹ РІ СЂР°Р·РЅС‹С… СЃС‚РёР»СЏС…
variants = await enhancer.generate_style_variants(
    user_id,
    photo_url,
    [PhotoStyle.PROFESSIONAL, PhotoStyle.LINKEDIN, PhotoStyle.CORPORATE]
)
```

**Р’РѕР·РјРѕР¶РЅРѕСЃС‚Рё:**

- РЈРґР°Р»РµРЅРёРµ С„РѕРЅР°
- РљРѕСЂСЂРµРєС†РёСЏ РѕСЃРІРµС‰РµРЅРёСЏ
- Р¦РІРµС‚РѕРєРѕСЂСЂРµРєС†РёСЏ
- РЎРіР»Р°Р¶РёРІР°РЅРёРµ РєРѕР¶Рё
- РџСЂРѕС„РµСЃСЃРёРѕРЅР°Р»СЊРЅС‹Р№ С„РѕРЅ
- РЎС‚РёР»Рё: natural, professional, corporate, linkedin

### 4. **test_cv_saga_integration.py** - РРЅС‚РµРіСЂР°С†РёРѕРЅРЅС‹Рµ С‚РµСЃС‚С‹

Р РµР°Р»РёСЃС‚РёС‡РЅС‹Рµ С‚РµСЃС‚С‹ СЃ СЃРёРјСѓР»СЏС†РёРµР№ РєР»РёРµРЅС‚СЃРєРёС… Р·Р°РїСЂРѕСЃРѕРІ:

```python
# Р—Р°РїСѓСЃС‚РёС‚СЊ РІСЃРµ С‚РµСЃС‚С‹
python -m pytest app/realtime/optimized/test_cv_saga_integration.py -v

# РР»Рё РЅР°РїСЂСЏРјСѓСЋ
python app/realtime/optimized/test_cv_saga_integration.py
```

**РўРµСЃС‚С‹ РїРѕРєСЂС‹РІР°СЋС‚:**

1. вњ… РЎРѕР·РґР°РЅРёРµ CV РёР· РїСЂРѕСЃС‚РѕРіРѕ РІРІРѕРґР°
2. вњ… РЎРѕР·РґР°РЅРёРµ CV СЃ РґРµС‚Р°Р»СЊРЅРѕР№ РёРЅС„РѕСЂРјР°С†РёРµР№
3. вњ… РџСЂРёРјРµРЅРµРЅРёРµ РїСЂР°РІРѕРє Рё РІРµСЂСЃРёРѕРЅРёСЂРѕРІР°РЅРёРµ
4. вњ… РћС‚РєР°С‚ Рє РїСЂРµРґС‹РґСѓС‰РµР№ РІРµСЂСЃРёРё
5. вњ… РЈР»СѓС‡С€РµРЅРёРµ С„РѕС‚РѕРіСЂР°С„РёРё
6. вњ… РџРѕР»РЅС‹Р№ Р¶РёР·РЅРµРЅРЅС‹Р№ С†РёРєР» CV
7. вњ… РџР°СЂР°Р»Р»РµР»СЊРЅРѕРµ СЃРѕР·РґР°РЅРёРµ РЅРµСЃРєРѕР»СЊРєРёС… CV

---

## рџљЂ Quick Start

### РџСЂРёРјРµСЂ 1: РЎРѕР·РґР°РЅРёРµ CV

```python
from app.core.realtime.optimized.cv_processor import CVProcessor
from app.core.realtime.optimized.cv_contracts import (
    CVGenerationRequest,
    CVConfiguration,
    CVStyle,
    CVLength
)

# РРЅРёС†РёР°Р»РёР·Р°С†РёСЏ
processor = CVProcessor()

# Р—Р°РїСЂРѕСЃ РѕС‚ РєР»РёРµРЅС‚Р° (СЃРёРјСѓР»СЏС†РёСЏ "РЎРґРµР»Р°Р№ CV")
request = CVGenerationRequest(
    user_id="user_123",
    user_input="""
        РњРµРЅСЏ Р·РѕРІСѓС‚ РђР»РµРєСЃР°РЅРґСЂ РџРµС‚СЂРѕРІ. Email: alex@example.com, С‚РµР»РµС„РѕРЅ +7 999 888 7766.
        Р Р°Р±РѕС‚Р°СЋ Python СЂР°Р·СЂР°Р±РѕС‚С‡РёРєРѕРј 7 Р»РµС‚. РЎРїРµС†РёР°Р»РёР·Р°С†РёСЏ - backend, FastAPI, РјРёРєСЂРѕСЃРµСЂРІРёСЃС‹.
        РћРєРѕРЅС‡РёР» РњР“РЈ РїРѕ СЃРїРµС†РёР°Р»СЊРЅРѕСЃС‚Рё РїСЂРёРєР»Р°РґРЅР°СЏ РјР°С‚РµРјР°С‚РёРєР°.
        РЎРµР№С‡Р°СЃ СЂР°Р±РѕС‚Р°СЋ РІ TechCorp РЅР° РїРѕР·РёС†РёРё Senior Python Developer.
        РћСЃРЅРѕРІРЅС‹Рµ РЅР°РІС‹РєРё: Python, FastAPI, PostgreSQL, Docker, AWS, Kubernetes.
        
        Р”РѕСЃС‚РёР¶РµРЅРёСЏ:
        - РћРїС‚РёРјРёР·РёСЂРѕРІР°Р» API, СЃРЅРёР·РёРІ latency РЅР° 70%
        - Р’РЅРµРґСЂРёР» event-driven Р°СЂС…РёС‚РµРєС‚СѓСЂСѓ
        - РџСЂРѕРІРµР» РјРµРЅС‚РѕСЂРёРЅРі 5 junior СЂР°Р·СЂР°Р±РѕС‚С‡РёРєРѕРІ
    """,
    configuration=CVConfiguration(
        style=CVStyle.PROFESSIONAL,
        length=CVLength.TWO_PAGES,
        target_position="Lead Python Developer",
        target_industry="FinTech",
        include_photo=True,
        language="ru"
    )
)

# Р“РµРЅРµСЂР°С†РёСЏ CV
response = await processor.generate_cv(request)

print(f"вњ… CV СЃРѕР·РґР°РЅРѕ: version {response.version_number}")
print(f"Completeness: {response.completeness_score:.1%}")
print(f"Recommendations: {response.recommendations}")
```

### РџСЂРёРјРµСЂ 2: Р’РЅРµСЃРµРЅРёРµ РїСЂР°РІРѕРє

```python
from app.core.realtime.optimized.cv_contracts import CVUpdateRequest

# РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ С…РѕС‡РµС‚ РѕР±РЅРѕРІРёС‚СЊ С‚РµР»РµС„РѕРЅ Рё email
update_request = CVUpdateRequest(
    version_id=response.version_id,
    user_id="user_123",
    updates={
        "personal_info.phone": "+7 111 222 3333",
        "personal_info.email": "alex.new@example.com",
        "personal_info.linkedin": "https://linkedin.com/in/alexpetrov"
    },
    change_description="РћР±РЅРѕРІРёР» РєРѕРЅС‚Р°РєС‚РЅСѓСЋ РёРЅС„РѕСЂРјР°С†РёСЋ",
    create_new_version=True  # РЎРѕР·РґР°С‚СЊ РЅРѕРІСѓСЋ РІРµСЂСЃРёСЋ
)

updated = await processor.update_cv(update_request)
print(f"вњ… РћР±РЅРѕРІР»РµРЅРѕ: version {updated.version_number}")
```

### РџСЂРёРјРµСЂ 3: Р”РѕР±Р°РІР»РµРЅРёРµ РґРѕСЃС‚РёР¶РµРЅРёСЏ Рє РѕРїС‹С‚Сѓ СЂР°Р±РѕС‚С‹

```python
# РћР±РЅРѕРІРёС‚СЊ РїРµСЂРІСѓСЋ РїРѕР·РёС†РёСЋ РІ РѕРїС‹С‚Рµ СЂР°Р±РѕС‚С‹
update_request = CVUpdateRequest(
    version_id=response.version_id,
    user_id="user_123",
    updates={
        "work_experience[0].achievements": [
            "РћРїС‚РёРјРёР·РёСЂРѕРІР°Р» API, СЃРЅРёР·РёРІ latency РЅР° 70%",
            "Р’РЅРµРґСЂРёР» event-driven Р°СЂС…РёС‚РµРєС‚СѓСЂСѓ, СѓРІРµР»РёС‡РёРІ throughput РІ 5 СЂР°Р·",
            "РџСЂРѕРІРµР» РјРµРЅС‚РѕСЂРёРЅРі 5 junior СЂР°Р·СЂР°Р±РѕС‚С‡РёРєРѕРІ",
            "РќРћР’РћР•: Р Р°Р·СЂР°Р±РѕС‚Р°Р» РІРЅСѓС‚СЂРµРЅРЅРёР№ С„СЂРµР№РјРІРѕСЂРє, РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РІ 20 РїСЂРѕРµРєС‚Р°С…"  # <-- РЅРѕРІРѕРµ
        ]
    },
    change_description="Р”РѕР±Р°РІРёР» РЅРѕРІРѕРµ РґРѕСЃС‚РёР¶РµРЅРёРµ",
    create_new_version=True
)

updated = await processor.update_cv(update_request)
```

### РџСЂРёРјРµСЂ 4: РћС‚РєР°С‚ РёР·РјРµРЅРµРЅРёР№

```python
# РџРѕР»СѓС‡РёС‚СЊ РІСЃРµ РІРµСЂСЃРёРё
versions = await processor.version_store.get_user_versions("user_123")

print("РСЃС‚РѕСЂРёСЏ РІРµСЂСЃРёР№:")
for v in versions:
    print(f"  v{v.version_number}: {v.change_description}")

# РћС‚РєР°С‚РёС‚СЊСЃСЏ Рє РІРµСЂСЃРёРё 2
rolled_back = await processor.rollback_to_version(
    user_id="user_123",
    target_version_id=versions[2].version_id  # v2
)

print(f"вњ… РћС‚РєР°С‚ РІС‹РїРѕР»РЅРµРЅ, СЃРѕР·РґР°РЅР° РЅРѕРІР°СЏ РІРµСЂСЃРёСЏ v{rolled_back.version_number}")
```

### РџСЂРёРјРµСЂ 5: РЈР»СѓС‡С€РµРЅРёРµ С„РѕС‚РѕРіСЂР°С„РёРё

```python
from app.core.realtime.optimized.cv_photo_enhancer import PhotoEnhancer
from app.core.realtime.optimized.cv_contracts import (
    PhotoEnhancementRequest,
    PhotoStyle
)

enhancer = PhotoEnhancer()

# Р—Р°РїСЂРѕСЃ РЅР° СѓР»СѓС‡С€РµРЅРёРµ
photo_request = PhotoEnhancementRequest(
    user_id="user_123",
    photo_url="https://example.com/photos/original.jpg",
    style=PhotoStyle.PROFESSIONAL,
    enhancements=[
        "background_removal",
        "lighting_adjustment",
        "color_correction",
        "skin_smoothing"
    ],
    remove_background=True,
    background_color="#F5F5F5"
)

photo_response = await enhancer.enhance_photo(photo_request)

print(f"вњ… Р¤РѕС‚Рѕ СѓР»СѓС‡С€РµРЅРѕ Р·Р° {photo_response.processing_time_ms:.0f}ms")
print(f"РЈР»СѓС‡С€РµРЅРЅРѕРµ С„РѕС‚Рѕ: {photo_response.enhanced_photo_url}")
print(f"Р РµРєРѕРјРµРЅРґР°С†РёРё: {photo_response.recommendations}")

# Р”РѕР±Р°РІРёС‚СЊ СѓР»СѓС‡С€РµРЅРЅРѕРµ С„РѕС‚Рѕ РІ CV
update_photo = CVUpdateRequest(
    version_id=response.version_id,
    user_id="user_123",
    updates={
        "personal_info.photo_url": photo_response.enhanced_photo_url,
        "personal_info.photo_enhanced": True,
        "personal_info.photo_style": PhotoStyle.PROFESSIONAL.value
    },
    change_description="Р”РѕР±Р°РІРёР» СѓР»СѓС‡С€РµРЅРЅСѓСЋ С„РѕС‚РѕРіСЂР°С„РёСЋ",
    create_new_version=True
)

cv_with_photo = await processor.update_cv(update_photo)
print(f"вњ… Р¤РѕС‚Рѕ РґРѕР±Р°РІР»РµРЅРѕ РІ CV v{cv_with_photo.version_number}")
```

---

## рџ“Љ РЎС‚СЂСѓРєС‚СѓСЂР° РєРѕРЅС‚СЂР°РєС‚РѕРІ

### CVData - РџРѕР»РЅР°СЏ СЃС‚СЂСѓРєС‚СѓСЂР° CV

```python
CVData(
    configuration=CVConfiguration(
        style=CVStyle.PROFESSIONAL,
        length=CVLength.TWO_PAGES,
        include_photo=True,
        target_position="Senior Developer"
    ),
    personal_info=PersonalInfo(
        first_name="РРІР°РЅ",
        last_name="РџРµС‚СЂРѕРІ",
        email="ivan@example.com",
        phone="+7 999 123 4567",
        location="РњРѕСЃРєРІР°, Р РѕСЃСЃРёСЏ",
        linkedin="https://linkedin.com/in/ivanpetrov",
        github="https://github.com/ivanpetrov",
        photo_url="...",
        photo_enhanced=True
    ),
    professional_summary=ProfessionalSummary(
        title="Senior Python Developer",
        summary="Experienced developer with 7+ years...",
        years_of_experience=7,
        experience_level=ExperienceLevel.SENIOR,
        key_skills=["Python", "FastAPI", "PostgreSQL", "Docker"]
    ),
    work_experience=[
        WorkExperience(
            company="TechCorp",
            position="Senior Python Developer",
            start_date=date(2020, 1, 1),
            end_date=None,
            is_current=True,
            description="Backend development with FastAPI...",
            achievements=[
                "Optimized API latency by 70%",
                "Implemented event-driven architecture",
                "Mentored 5 junior developers"
            ],
            technologies=["Python", "FastAPI", "PostgreSQL"]
        )
    ],
    education=[...],
    skills=[
        SkillCategory(
            category="Programming Languages",
            skills=["Python", "JavaScript", "Go"],
            proficiency_level="expert"
        )
    ]
)
```

---

## рџ”„ Р’РµСЂСЃРёРѕРЅРёСЂРѕРІР°РЅРёРµ

РљР°Р¶РґРѕРµ РёР·РјРµРЅРµРЅРёРµ CV СЃРѕР·РґР°РµС‚ РЅРѕРІСѓСЋ РІРµСЂСЃРёСЋ (РµСЃР»Рё `create_new_version=True`):

```
v1: Initial CV creation
  в†“
v2: Updated contact info
  в†“
v3: Added photo
  в†“
v4: Added detailed work experience
  в†“
v5: Rollback to v2 (new version with v2 data)
```

**Р’Р°Р¶РЅРѕ:**
- РСЃС‚РѕСЂРёСЏ РїРѕР»РЅРѕСЃС‚СЊСЋ СЃРѕС…СЂР°РЅСЏРµС‚СЃСЏ
- РћС‚РєР°С‚ СЃРѕР·РґР°РµС‚ РЅРѕРІСѓСЋ РІРµСЂСЃРёСЋ СЃ РґР°РЅРЅС‹РјРё РёР· С†РµР»РµРІРѕР№
- РњРѕР¶РЅРѕ РїРѕР»СѓС‡РёС‚СЊ diff РјРµР¶РґСѓ Р»СЋР±С‹РјРё РІРµСЂСЃРёСЏРјРё
- РљР°Р¶РґР°СЏ РІРµСЂСЃРёСЏ РёРјРµРµС‚ `parent_version_id` РґР»СЏ РїРѕСЃС‚СЂРѕРµРЅРёСЏ С†РµРїРѕС‡РєРё

---

## рџЋЁ РЎС‚РёР»Рё CV

### Professional (СЂРµРєРѕРјРµРЅРґСѓРµС‚СЃСЏ РґР»СЏ РєРѕСЂРїРѕСЂР°С†РёР№)
- РљР»Р°СЃСЃРёС‡РµСЃРєРёР№ РєРѕСЂРїРѕСЂР°С‚РёРІРЅС‹Р№ РґРёР·Р°Р№РЅ
- РќРµР№С‚СЂР°Р»СЊРЅС‹Рµ С†РІРµС‚Р°
- Р§РµС‚РєР°СЏ СЃС‚СЂСѓРєС‚СѓСЂР°
- РђРєС†РµРЅС‚ РЅР° РґРѕСЃС‚РёР¶РµРЅРёСЏ

### Modern (РґР»СЏ СЃС‚Р°СЂС‚Р°РїРѕРІ)
- РЎРѕРІСЂРµРјРµРЅРЅС‹Р№ РјРёРЅРёРјР°Р»РёСЃС‚РёС‡РЅС‹Р№
- Р§РёСЃС‚С‹Рµ Р»РёРЅРёРё
- Р‘РѕР»СЊС€Рµ white space
- РђРєС†РµРЅС‚ РЅР° РЅР°РІС‹РєРё

### Creative (РґР»СЏ РґРёР·Р°Р№РЅРµСЂРѕРІ)
- РљСЂРµР°С‚РёРІРЅС‹Р№ РґРёР·Р°Р№РЅ
- РЇСЂРєРёРµ Р°РєС†РµРЅС‚С‹
- РќРµСЃС‚Р°РЅРґР°СЂС‚РЅР°СЏ СЃС‚СЂСѓРєС‚СѓСЂР°
- Р’РёР·СѓР°Р»СЊРЅС‹Рµ СЌР»РµРјРµРЅС‚С‹

### Technical (РґР»СЏ РёРЅР¶РµРЅРµСЂРѕРІ)
- РўРµС…РЅРёС‡РµСЃРєРёР№ СЃС‚РёР»СЊ
- Р”РµС‚Р°Р»СЊРЅР°СЏ СЃС‚СЂСѓРєС‚СѓСЂР°
- РђРєС†РµРЅС‚ РЅР° С‚РµС…РЅРѕР»РѕРіРёРё
- РўР°Р±Р»РёС†С‹ Рё СЃС…РµРјС‹

### Academic (РґР»СЏ РЅР°СѓРєРё)
- РђРєР°РґРµРјРёС‡РµСЃРєРёР№ С„РѕСЂРјР°С‚
- РџСѓР±Р»РёРєР°С†РёРё
- РСЃСЃР»РµРґРѕРІР°РЅРёСЏ
- Р”РµС‚Р°Р»СЊРЅРѕРµ РѕР±СЂР°Р·РѕРІР°РЅРёРµ

---

## рџ“· РЈР»СѓС‡С€РµРЅРёРµ С„РѕС‚РѕРіСЂР°С„РёР№

### Р”РѕСЃС‚СѓРїРЅС‹Рµ СЃС‚РёР»Рё:

1. **Natural** - Р•СЃС‚РµСЃС‚РІРµРЅРЅР°СЏ СЂРµС‚СѓС€СЊ
   - РњРёРЅРёРјР°Р»СЊРЅР°СЏ РѕР±СЂР°Р±РѕС‚РєР°
   - РЎРѕС…СЂР°РЅРµРЅРёРµ РµСЃС‚РµСЃС‚РІРµРЅРЅРѕСЃС‚Рё
   - Р›РµРіРєР°СЏ РєРѕСЂСЂРµРєС†РёСЏ

2. **Professional** - РџСЂРѕС„РµСЃСЃРёРѕРЅР°Р»СЊРЅР°СЏ СЃС‚СѓРґРёР№РЅР°СЏ
   - РЎС‚СѓРґРёР№РЅРѕРµ РѕСЃРІРµС‰РµРЅРёРµ
   - РќРµР№С‚СЂР°Р»СЊРЅС‹Р№ С„РѕРЅ
   - Р§РµС‚РєРёР№ С„РѕРєСѓСЃ

3. **Corporate** - РљРѕСЂРїРѕСЂР°С‚РёРІРЅС‹Р№ СЃС‚РёР»СЊ
   - Р‘РµР»С‹Р№ С„РѕРЅ
   - Р”РµР»РѕРІРѕР№ СЃС‚РёР»СЊ
   - Р’С‹СЃРѕРєР°СЏ С‡РµС‚РєРѕСЃС‚СЊ

4. **LinkedIn** - LinkedIn-СЃС‚РёР»СЊ
   - РџСЂРёРІРµС‚Р»РёРІРѕРµ РІС‹СЂР°Р¶РµРЅРёРµ
   - РњСЏРіРєРёР№ РіРѕР»СѓР±РѕР№ С„РѕРЅ
   - РџСЂРѕС„РµСЃСЃРёРѕРЅР°Р»СЊРЅРѕ-РґСЂСѓР¶РµР»СЋР±РЅС‹Р№

### Р”РѕСЃС‚СѓРїРЅС‹Рµ СѓР»СѓС‡С€РµРЅРёСЏ:

- `background_removal` - РЈРґР°Р»РµРЅРёРµ С„РѕРЅР°
- `lighting_adjustment` - РљРѕСЂСЂРµРєС†РёСЏ РѕСЃРІРµС‰РµРЅРёСЏ
- `color_correction` - Р¦РІРµС‚РѕРєРѕСЂСЂРµРєС†РёСЏ
- `skin_smoothing` - РЎРіР»Р°Р¶РёРІР°РЅРёРµ РєРѕР¶Рё
- `professional_background` - РџСЂРѕС„РµСЃСЃРёРѕРЅР°Р»СЊРЅС‹Р№ С„РѕРЅ

---

## вњ… Р’Р°Р»РёРґР°С†РёСЏ Рё Completeness Score

РЎРёСЃС‚РµРјР° Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РѕС†РµРЅРёРІР°РµС‚ РїРѕР»РЅРѕС‚Сѓ CV:

```python
response.completeness_score  # 0.0 - 1.0
response.missing_sections    # ["education", "skills"]
response.recommendations     # ["Р”РѕР±Р°РІСЊС‚Рµ РѕР±СЂР°Р·РѕРІР°РЅРёРµ", "РЈРєР°Р¶РёС‚Рµ РЅР°РІС‹РєРё"]
```

**Р¤Р°РєС‚РѕСЂС‹ РѕС†РµРЅРєРё:**

- вњ… Professional Summary: +20%
- вњ… Work Experience: +30%
- вњ… Education: +20%
- вњ… Skills: +15%
- вњ… Photo: +10%
- вњ… Social Links (LinkedIn/GitHub): +5%

**Р РµРєРѕРјРµРЅРґР°С†РёРё:**

- РћС‚СЃСѓС‚СЃС‚РІСѓСЋС‰РёРµ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹Рµ СЃРµРєС†РёРё
- РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅС‹Рµ РґР°РЅРЅС‹Рµ РІ СЃРµРєС†РёСЏС…
- РћС‚СЃСѓС‚СЃС‚РІРёРµ РјРµС‚СЂРёРє РІ РґРѕСЃС‚РёР¶РµРЅРёСЏС…
- РќРµС‚ С„РѕС‚РѕРіСЂР°С„РёРё
- РћС‚СЃСѓС‚СЃС‚РІРёРµ СЃРѕС†РёР°Р»СЊРЅС‹С… РїСЂРѕС„РёР»РµР№

---

## рџ§Є Р—Р°РїСѓСЃРє С‚РµСЃС‚РѕРІ

```bash
# РЈСЃС‚Р°РЅРѕРІРєР° Р·Р°РІРёСЃРёРјРѕСЃС‚РµР№
pip install pytest pytest-asyncio pydantic fastapi

# Р—Р°РїСѓСЃРє РІСЃРµС… С‚РµСЃС‚РѕРІ
pytest app/realtime/optimized/test_cv_saga_integration.py -v

# Р—Р°РїСѓСЃРє РєРѕРЅРєСЂРµС‚РЅРѕРіРѕ С‚РµСЃС‚Р°
pytest app/realtime/optimized/test_cv_saga_integration.py::test_create_cv_from_simple_input -v

# Р—Р°РїСѓСЃРє СЃ РїРѕРґСЂРѕР±РЅС‹Рј РІС‹РІРѕРґРѕРј
python app/realtime/optimized/test_cv_saga_integration.py
```

**Р’С‹РІРѕРґ С‚РµСЃС‚РѕРІ:**

```
==================================================================
CV CREATION SYSTEM - INTEGRATION TESTS
==================================================================

рџ§Є TEST 1: РЎРѕР·РґР°РЅРёРµ CV РёР· РїСЂРѕСЃС‚РѕРіРѕ РІРІРѕРґР°
вњ… CV СЃРѕР·РґР°РЅРѕ: version 1
   Completeness: 45%
   Recommendations: 3

рџ§Є TEST 2: РЎРѕР·РґР°РЅРёРµ CV СЃ РґРµС‚Р°Р»СЊРЅРѕР№ РёРЅС„РѕСЂРјР°С†РёРµР№
вњ… Р”РµС‚Р°Р»СЊРЅРѕРµ CV СЃРѕР·РґР°РЅРѕ: version 1
   Completeness: 87%
   Missing sections: []

рџ§Є TEST 3: РџСЂРёРјРµРЅРµРЅРёРµ РїСЂР°РІРѕРє Рё РІРµСЂСЃРёРѕРЅРёСЂРѕРІР°РЅРёРµ
рџ“ќ РЎРѕР·РґР°РЅРѕ РЅР°С‡Р°Р»СЊРЅРѕРµ CV: v1
вњЏпёЏ  РћР±РЅРѕРІР»РµРЅРѕ CV: v2
   РР·РјРµРЅРµРЅРёРµ: РћР±РЅРѕРІРёР» РєРѕРЅС‚Р°РєС‚РЅСѓСЋ РёРЅС„РѕСЂРјР°С†РёСЋ
вњЏпёЏ  РћР±РЅРѕРІР»РµРЅРѕ CV: v3
рџ“љ РСЃС‚РѕСЂРёСЏ РІРµСЂСЃРёР№: 3 РІРµСЂСЃРёР№

...Рё С‚.Рґ.

==================================================================
вњ… Р’РЎР• РўР•РЎРўР« РџР РћР™Р”Р•РќР« РЈРЎРџР•РЁРќРћ
==================================================================
```

---

## рџ”Њ РРЅС‚РµРіСЂР°С†РёСЏ СЃ FastAPI

РџСЂРёРјРµСЂ REST API endpoints:

```python
from fastapi import FastAPI, HTTPException
from app.core.realtime.optimized.cv_processor import CVProcessor
from app.core.realtime.optimized.cv_contracts import (
    CVGenerationRequest,
    CVUpdateRequest
)

app = FastAPI()
processor = CVProcessor()

@app.post("/api/cv/generate")
async def generate_cv(request: CVGenerationRequest):
    """РЎРѕР·РґР°С‚СЊ CV РёР· РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРіРѕ РІРІРѕРґР°."""
    try:
        response = await processor.generate_cv(request)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cv/update")
async def update_cv(request: CVUpdateRequest):
    """РџСЂРёРјРµРЅРёС‚СЊ РїСЂР°РІРєРё Рє CV."""
    try:
        response = await processor.update_cv(request)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cv/rollback/{user_id}/{target_version_id}")
async def rollback_cv(user_id: str, target_version_id: str):
    """РћС‚РєР°С‚РёС‚СЊ Рє РїСЂРµРґС‹РґСѓС‰РµР№ РІРµСЂСЃРёРё."""
    try:
        response = await processor.rollback_to_version(user_id, target_version_id)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cv/versions/{user_id}")
async def get_versions(user_id: str):
    """РџРѕР»СѓС‡РёС‚СЊ РІСЃРµ РІРµСЂСЃРёРё CV РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ."""
    versions = await processor.version_store.get_user_versions(user_id)
    return {"versions": versions}
```

---

## рџ“ќ TODO / Roadmap

### РўРµРєСѓС‰Р°СЏ СЂРµР°Р»РёР·Р°С†РёСЏ (Mock):
- вњ… РљРѕРЅС‚СЂР°РєС‚С‹ РґР°РЅРЅС‹С… (Pydantic)
- вњ… Р’РµСЂСЃРёРѕРЅРёСЂРѕРІР°РЅРёРµ
- вњ… РћС‚РєР°С‚ РёР·РјРµРЅРµРЅРёР№
- вњ… Р’Р°Р»РёРґР°С†РёСЏ Рё completeness score
- вњ… РРЅС‚РµРіСЂР°С†РёРѕРЅРЅС‹Рµ С‚РµСЃС‚С‹

### РўСЂРµР±СѓРµС‚СЃСЏ РёРЅС‚РµРіСЂР°С†РёСЏ:

1. **LLM РґР»СЏ РїР°СЂСЃРёРЅРіР° user input:**
   - GPT-4 / Claude / Gemini РґР»СЏ structured output
   - РџСЂРѕРјРїС‚-РёРЅР¶РµРЅРµСЂРёСЏ РґР»СЏ РёР·РІР»РµС‡РµРЅРёСЏ СЃС‚СЂСѓРєС‚СѓСЂРёСЂРѕРІР°РЅРЅС‹С… РґР°РЅРЅС‹С…
   
2. **Р‘Р°Р·Р° РґР°РЅРЅС‹С…:**
   - PostgreSQL РґР»СЏ С…СЂР°РЅРµРЅРёСЏ РІРµСЂСЃРёР№
   - Redis РґР»СЏ РєСЌС€РёСЂРѕРІР°РЅРёСЏ
   
3. **AI РјРѕРґРµР»Рё РґР»СЏ С„РѕС‚РѕРіСЂР°С„РёР№:**
   - Stability AI / Replicate РґР»СЏ РіРµРЅРµСЂР°С†РёРё
   - Remove.bg РґР»СЏ СѓРґР°Р»РµРЅРёСЏ С„РѕРЅР°
   - Face++ РґР»СЏ РѕР±СЂР°Р±РѕС‚РєРё Р»РёС†Р°
   
4. **РҐСЂР°РЅРёР»РёС‰Рµ С„Р°Р№Р»РѕРІ:**
   - S3 / CDN РґР»СЏ С…СЂР°РЅРµРЅРёСЏ С„РѕС‚Рѕ Рё PDF
   
5. **PDF РіРµРЅРµСЂР°С†РёСЏ:**
   - ReportLab / WeasyPrint РґР»СЏ СЃРѕР·РґР°РЅРёСЏ PDF
   - РЁР°Р±Р»РѕРЅС‹ РґР»СЏ СЂР°Р·РЅС‹С… СЃС‚РёР»РµР№

---

## рџЋЇ РљР»СЋС‡РµРІС‹Рµ РѕСЃРѕР±РµРЅРЅРѕСЃС‚Рё

### 1. Free-form Input
РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РјРѕР¶РµС‚ РЅР°РїРёСЃР°С‚СЊ РІ СЃРІРѕР±РѕРґРЅРѕР№ С„РѕСЂРјРµ, СЃРёСЃС‚РµРјР° РёР·РІР»РµС‡РµС‚ СЃС‚СЂСѓРєС‚СѓСЂРёСЂРѕРІР°РЅРЅС‹Рµ РґР°РЅРЅС‹Рµ.

### 2. РџРѕР»РЅРѕРµ РІРµСЂСЃРёРѕРЅРёСЂРѕРІР°РЅРёРµ
РљР°Р¶РґРѕРµ РёР·РјРµРЅРµРЅРёРµ СЃРѕС…СЂР°РЅСЏРµС‚СЃСЏ, РјРѕР¶РЅРѕ РѕС‚РєР°С‚РёС‚СЊСЃСЏ Рє Р»СЋР±РѕР№ РІРµСЂСЃРёРё.

### 3. Р’Р°Р»РёРґР°С†РёСЏ РІ СЂРµР°Р»СЊРЅРѕРј РІСЂРµРјРµРЅРё
РЎРёСЃС‚РµРјР° РїСЂРѕРІРµСЂСЏРµС‚ РїРѕР»РЅРѕС‚Сѓ Рё РґР°РµС‚ СЂРµРєРѕРјРµРЅРґР°С†РёРё РїРѕ СѓР»СѓС‡С€РµРЅРёСЋ.

### 4. AI-СѓР»СѓС‡С€РµРЅРёРµ С„РѕС‚РѕРіСЂР°С„РёР№
РђРІС‚РѕРјР°С‚РёС‡РµСЃРєР°СЏ РѕР±СЂР°Р±РѕС‚РєР° С„РѕС‚Рѕ РґР»СЏ РїСЂРѕС„РµСЃСЃРёРѕРЅР°Р»СЊРЅРѕРіРѕ РІРёРґР°.

### 5. РўРёРїРѕР±РµР·РѕРїР°СЃРЅРѕСЃС‚СЊ
Р’СЃРµ РєРѕРЅС‚СЂР°РєС‚С‹ СЃС‚СЂРѕРіРѕ С‚РёРїРёР·РёСЂРѕРІР°РЅС‹ С‡РµСЂРµР· Pydantic v2.

### 6. РђСЃРёРЅС…СЂРѕРЅРЅРѕСЃС‚СЊ
РџРѕР»РЅР°СЏ РїРѕРґРґРµСЂР¶РєР° async/await РґР»СЏ РІС‹СЃРѕРєРѕР№ РїСЂРѕРёР·РІРѕРґРёС‚РµР»СЊРЅРѕСЃС‚Рё.

### 7. Р Р°СЃС€РёСЂСЏРµРјРѕСЃС‚СЊ
Р›РµРіРєРѕ РґРѕР±Р°РІРёС‚СЊ РЅРѕРІС‹Рµ СЃРµРєС†РёРё С‡РµСЂРµР· `custom_sections`.

---

## рџ“ћ Support

Р”Р»СЏ РІРѕРїСЂРѕСЃРѕРІ Рё РїСЂРµРґР»РѕР¶РµРЅРёР№:
- Р”РѕРєСѓРјРµРЅС‚Р°С†РёСЏ: README.md
- РўРµСЃС‚С‹: test_cv_saga_integration.py
- РџСЂРёРјРµСЂС‹: СЃРј. СЃРµРєС†РёСЋ Quick Start

---

**Р“РѕС‚РѕРІРѕ Рє РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЋ!** рџЋ‰

РЎРёСЃС‚РµРјР° РїРѕР»РЅРѕСЃС‚СЊСЋ С„СѓРЅРєС†РёРѕРЅР°Р»СЊРЅР° СЃ mock-Р°РґР°РїС‚РµСЂР°РјРё.
Р”Р»СЏ РїСЂРѕРґР°РєС€РµРЅР° С‚СЂРµР±СѓРµС‚СЃСЏ РёРЅС‚РµРіСЂР°С†РёСЏ LLM, Р‘Р”, Рё AI-РјРѕРґРµР»РµР№.

