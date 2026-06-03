# Optimizer System - Multi-Version Optimization Framework

Р Р°СЃС€РёСЂРµРЅРЅР°СЏ СЃРёСЃС‚РµРјР° РѕРїС‚РёРјРёР·Р°С†РёРё СЃ РїРѕРґРґРµСЂР¶РєРѕР№ РІРµСЂСЃРёРѕРЅРёСЂРѕРІР°РЅРёСЏ Рё РјРЅРѕР¶РµСЃС‚РІРµРЅРЅС‹С… С†РµР»РµР№ РѕРїС‚РёРјРёР·Р°С†РёРё.

## рџ“‹ РћРіР»Р°РІР»РµРЅРёРµ

- [Р’РѕР·РјРѕР¶РЅРѕСЃС‚Рё](#РІРѕР·РјРѕР¶РЅРѕСЃС‚Рё)
- [РђСЂС…РёС‚РµРєС‚СѓСЂР°](#Р°СЂС…РёС‚РµРєС‚СѓСЂР°)
- [Р’РµСЂСЃРёРё РѕРїС‚РёРјРёР·Р°С‚РѕСЂРѕРІ](#РІРµСЂСЃРёРё-РѕРїС‚РёРјРёР·Р°С‚РѕСЂРѕРІ)
- [Р‘С‹СЃС‚СЂС‹Р№ СЃС‚Р°СЂС‚](#Р±С‹СЃС‚СЂС‹Р№-СЃС‚Р°СЂС‚)
- [РСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ](#РёСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ)
- [РџСЂРёРјРµСЂС‹](#РїСЂРёРјРµСЂС‹)

## рџЋЇ Р’РѕР·РјРѕР¶РЅРѕСЃС‚Рё

### Р§С‚Рѕ РјРѕР¶РЅРѕ РѕРїС‚РёРјРёР·РёСЂРѕРІР°С‚СЊ

1. **РџСЂРѕРјРїС‚С‹ (Prompts)**
   - ContentCreator prompt
   - LessonPlanner prompt
   - Validator prompt

2. **Р’Р°Р»РёРґР°С†РёСЏ (Validation)**
   - РџСЂР°РІРёР»Р° РІР°Р»РёРґР°С†РёРё
   - Р’РµСЃР° РїСЂР°РІРёР»
   - РџРѕСЂРѕРіРѕРІС‹Рµ Р·РЅР°С‡РµРЅРёСЏ

3. **РџР°СЂР°РјРµС‚СЂС‹ РїР°Р№РїР»Р°Р№РЅР°**
   - РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ С€Р°РіРѕРІ
   - РџР°СЂР°РјРµС‚СЂС‹ РјРѕРґРµР»РµР№

### РљР»СЋС‡РµРІС‹Рµ РѕСЃРѕР±РµРЅРЅРѕСЃС‚Рё

- вњ… **Р’РµСЂСЃРёРѕРЅРёСЂРѕРІР°РЅРёРµ** - РЅРµСЃРєРѕР»СЊРєРѕ РІРµСЂСЃРёР№ РѕРїС‚РёРјРёР·Р°С‚РѕСЂРѕРІ СЃРѕСЃСѓС‰РµСЃС‚РІСѓСЋС‚ Р±РµР· РєРѕРЅС„Р»РёРєС‚РѕРІ
- вњ… **Р“РёР±РєРѕРµ С‚РµСЃС‚РёСЂРѕРІР°РЅРёРµ** - РєР°СЃС‚РѕРјРЅС‹Рµ С‚РµСЃС‚РѕРІС‹Рµ РЅР°Р±РѕСЂС‹ РґР»СЏ СЂР°Р·РЅС‹С… С†РµР»РµР№
- вњ… **РС‚РµСЂР°С‚РёРІРЅРѕРµ СѓР»СѓС‡С€РµРЅРёРµ** - РёСЃРїРѕР»СЊР·СѓРµС‚ LLM РґР»СЏ РјРµС‚Р°-РѕРїС‚РёРјРёР·Р°С†РёРё
- вњ… **Р”РµС‚Р°Р»СЊРЅР°СЏ Р°РЅР°Р»РёС‚РёРєР°** - HTML Рё Markdown РѕС‚С‡РµС‚С‹
- вњ… **Р’РѕР·РѕР±РЅРѕРІР»РµРЅРёРµ** - РїСЂРѕРґРѕР»Р¶РµРЅРёРµ РѕРїС‚РёРјРёР·Р°С†РёРё СЃ С‚РѕС‡РєРё РѕСЃС‚Р°РЅРѕРІРєРё
- вњ… **РЎСЂР°РІРЅРµРЅРёРµ РІРµСЂСЃРёР№** - Р±РµРЅС‡РјР°СЂРєРё РјРµР¶РґСѓ СЂР°Р·РЅС‹РјРё РїРѕРґС…РѕРґР°РјРё

## рџЏ—пёЏ РђСЂС…РёС‚РµРєС‚СѓСЂР°

```
app/optimizer/
в”њв”Ђв”Ђ __init__.py          # РџСѓР±Р»РёС‡РЅС‹Р№ API
в”њв”Ђв”Ђ base.py              # Р‘Р°Р·РѕРІС‹Рµ РєР»Р°СЃСЃС‹ Рё РёРЅС‚РµСЂС„РµР№СЃС‹
в”њв”Ђв”Ђ optimizer_v1.py      # V1: РћРїС‚РёРјРёР·Р°С†РёСЏ РїСЂРѕРјРїС‚РѕРІ
в”њв”Ђв”Ђ optimizer_v2.py      # V2: РџСЂРѕРјРїС‚С‹ + РІР°Р»РёРґР°С†РёСЏ
в”њв”Ђв”Ђ manager.py           # Р¦РµРЅС‚СЂР°Р»СЊРЅС‹Р№ РјРµРЅРµРґР¶РµСЂ
в”њв”Ђв”Ђ testing.py           # РўРµСЃС‚РѕРІР°СЏ РёРЅС„СЂР°СЃС‚СЂСѓРєС‚СѓСЂР°
в””в”Ђв”Ђ cli.py               # РљРѕРјР°РЅРґРЅР°СЏ СЃС‚СЂРѕРєР°

optimizer_logs/          # Р РµР·СѓР»СЊС‚Р°С‚С‹ РѕРїС‚РёРјРёР·Р°С†РёРё
в”њв”Ђв”Ђ v1/                  # РЎРµСЃСЃРёРё V1
в”‚   в””в”Ђв”Ђ v1_prompt_content_creator_1234567890/
в”‚       в”њв”Ђв”Ђ prompts/     # РЎРѕС…СЂР°РЅРµРЅРЅС‹Рµ РїСЂРѕРјРїС‚С‹
в”‚       в”њв”Ђв”Ђ iteration_1/ # Р”РµС‚Р°Р»Рё РёС‚РµСЂР°С†РёР№
в”‚       в”њв”Ђв”Ђ final_report.json
в”‚       в”њв”Ђв”Ђ final_report.md
в”‚       в””в”Ђв”Ђ report.html
в”њв”Ђв”Ђ v2/                  # РЎРµСЃСЃРёРё V2
в””в”Ђв”Ђ comparisons/         # РЎСЂР°РІРЅРµРЅРёСЏ РІРµСЂСЃРёР№
```

## рџ”§ Р’РµСЂСЃРёРё РѕРїС‚РёРјРёР·Р°С‚РѕСЂРѕРІ

### V1 - Prompt-Only Optimization

**Р¦РµР»СЊ:** РћРїС‚РёРјРёР·Р°С†РёСЏ СЃРёСЃС‚РµРјРЅС‹С… РїСЂРѕРјРїС‚РѕРІ РґР»СЏ РіРµРЅРµСЂР°С†РёРё РєРѕРЅС‚РµРЅС‚Р°

**Р’РѕР·РјРѕР¶РЅРѕСЃС‚Рё:**
- РС‚РµСЂР°С‚РёРІРЅРѕРµ СѓР»СѓС‡С€РµРЅРёРµ РїСЂРѕРјРїС‚РѕРІ
- РђРЅР°Р»РёР· РЅРµСѓРґР°С‡РЅС‹С… С‚РµСЃС‚РѕРІ
- LLM-based СЂРµС„Р°Р№РЅРјРµРЅС‚
- РљРѕРЅС‚СЂРѕР»СЊ С‚РѕРєРµРЅРѕРІ (Р»РёРјРёС‚ 1500)

**РљРѕРіРґР° РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ:**
- РќСѓР¶РЅРѕ СѓР»СѓС‡С€РёС‚СЊ РєР°С‡РµСЃС‚РІРѕ РіРµРЅРµСЂРёСЂСѓРµРјРѕРіРѕ РєРѕРЅС‚РµРЅС‚Р°
- РџСЂРѕР±Р»РµРјС‹ СЃ С„РѕСЂРјР°С‚РѕРј РѕС‚РІРµС‚РѕРІ
- РќРµСЃРѕРѕС‚РІРµС‚СЃС‚РІРёРµ CEFR СѓСЂРѕРІРЅСЋ

**РџСЂРёРјРµСЂ:**
```python
from app.optimizer import OptimizerManager, OptimizationTarget, OptimizerVersion

manager = OptimizerManager()
result = await manager.run_optimization(
    version=OptimizerVersion.V1_PROMPT_ONLY,
    target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
    max_iterations=5
)
```

### V2 - Prompt + Validation Optimization

**Р¦РµР»СЊ:** РЎРѕРІРјРµСЃС‚РЅР°СЏ РѕРїС‚РёРјРёР·Р°С†РёСЏ РїСЂРѕРјРїС‚РѕРІ Рё РІР°Р»РёРґР°С†РёРѕРЅРЅС‹С… РїСЂР°РІРёР»

**Р’РѕР·РјРѕР¶РЅРѕСЃС‚Рё:**
- Р’СЃРµ РёР· V1
- РћРїС‚РёРјРёР·Р°С†РёСЏ РІР°Р»РёРґР°С†РёРѕРЅРЅС‹С… РїСЂР°РІРёР»
- РќР°СЃС‚СЂРѕР№РєР° РІРµСЃРѕРІ РїСЂР°РІРёР»
- Р‘Р°Р»Р°РЅСЃРёСЂРѕРІРєР° precision/recall
- Р’РѕР·РјРѕР¶РЅРѕСЃС‚СЊ РѕРїС‚РёРјРёР·РёСЂРѕРІР°С‚СЊ СЂР°Р·РґРµР»СЊРЅРѕ РёР»Рё РІРјРµСЃС‚Рµ

**РљРѕРіРґР° РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ:**
- РњРЅРѕРіРѕ Р»РѕР¶РЅС‹С… СЃСЂР°Р±Р°С‚С‹РІР°РЅРёР№ РІ РІР°Р»РёРґР°С†РёРё
- Р’Р°Р»РёРґР°С†РёСЏ СЃР»РёС€РєРѕРј СЃС‚СЂРѕРіР°СЏ РёР»Рё РјСЏРіРєР°СЏ
- РќСѓР¶РЅР° С‚РѕРЅРєР°СЏ РЅР°СЃС‚СЂРѕР№РєР° РїРѕРґ СЃРїРµС†РёС„РёС‡РµСЃРєРёРµ С‚СЂРµР±РѕРІР°РЅРёСЏ

**РџСЂРёРјРµСЂ:**
```python
# РћРїС‚РёРјРёР·Р°С†РёСЏ С‚РѕР»СЊРєРѕ РІР°Р»РёРґР°С†РёРё
result = await manager.run_optimization(
    version=OptimizerVersion.V2_PROMPT_VALIDATION,
    target=OptimizationTarget.VALIDATION_RULES,
    optimize_prompt=False,
    optimize_validation=True
)

# РћРїС‚РёРјРёР·Р°С†РёСЏ РѕР±РѕРёС…
result = await manager.run_optimization(
    version=OptimizerVersion.V2_PROMPT_VALIDATION,
    target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
    optimize_prompt=True,
    optimize_validation=True
)
```

### V3 - Multi-Target Optimization (РџР»Р°РЅРёСЂСѓРµС‚СЃСЏ)

**Р¦РµР»СЊ:** РћРґРЅРѕРІСЂРµРјРµРЅРЅР°СЏ РѕРїС‚РёРјРёР·Р°С†РёСЏ РјРЅРѕР¶РµСЃС‚РІРµРЅРЅС‹С… РєРѕРјРїРѕРЅРµРЅС‚РѕРІ

**РџР»Р°РЅРёСЂСѓРµРјС‹Рµ РІРѕР·РјРѕР¶РЅРѕСЃС‚Рё:**
- РћРїС‚РёРјРёР·Р°С†РёСЏ РІСЃРµС… РїСЂРѕРјРїС‚РѕРІ РІ РїР°Р№РїР»Р°Р№РЅРµ
- РџР°СЂР°РјРµС‚СЂС‹ РјРѕРґРµР»РµР№
- РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ РїР°Р№РїР»Р°Р№РЅР°
- Cross-component optimization

## рџљЂ Р‘С‹СЃС‚СЂС‹Р№ СЃС‚Р°СЂС‚

### 1. РЈСЃС‚Р°РЅРѕРІРєР° Р·Р°РІРёСЃРёРјРѕСЃС‚РµР№

Р’СЃРµ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё СѓР¶Рµ РІРєР»СЋС‡РµРЅС‹ РІ РѕСЃРЅРѕРІРЅРѕР№ `requirements.txt` РїСЂРѕРµРєС‚Р°.

### 2. Р‘Р°Р·РѕРІРѕРµ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ

#### Р§РµСЂРµР· CLI (СЂРµРєРѕРјРµРЅРґСѓРµС‚СЃСЏ РґР»СЏ РЅР°С‡РёРЅР°СЋС‰РёС…)

```bash
# РћРїС‚РёРјРёР·Р°С†РёСЏ РїСЂРѕРјРїС‚Р° ContentCreator (V1)
python -m app.services.optimizer.optimizer.cli \
    --version v1 \
    --target prompt_content_creator \
    --iterations 5

# РћРїС‚РёРјРёР·Р°С†РёСЏ РІР°Р»РёРґР°С†РёРё (V2)
python -m app.services.optimizer.optimizer.cli \
    --version v2 \
    --target validation_rules \
    --optimize-validation-only \
    --iterations 5

# РћРїС‚РёРјРёР·Р°С†РёСЏ РѕР±РѕРёС… (V2)
python -m app.services.optimizer.optimizer.cli \
    --version v2 \
    --target prompt_content_creator \
    --optimize-both \
    --iterations 10
```

#### Р§РµСЂРµР· Python API

```python
import asyncio
from app.optimizer import OptimizerManager, OptimizationTarget, OptimizerVersion

async def main():
    manager = OptimizerManager()
    
    # V1: РўРѕР»СЊРєРѕ РїСЂРѕРјРїС‚С‹
    result = await manager.run_optimization(
        version=OptimizerVersion.V1_PROMPT_ONLY,
        target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
        max_iterations=5
    )
    
    print(f"Final score: {result.best_iteration.avg_score:.1f}/100")
    print(f"Improvement: {result.improvement_delta:+.1f} points")

asyncio.run(main())
```

## рџ“љ РСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ

### Р Р°Р±РѕС‚Р° СЃ С‚РµСЃС‚РѕРІС‹РјРё СЃР»СѓС‡Р°СЏРјРё

#### РСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ СЃС‚Р°РЅРґР°СЂС‚РЅРѕРіРѕ РЅР°Р±РѕСЂР°

```python
from app.services.optimizer.optimizer.testing import TestCaseLoader

# Р—Р°РіСЂСѓР·РёС‚СЊ СЃС‚Р°РЅРґР°СЂС‚РЅС‹Р№ РЅР°Р±РѕСЂ
test_cases = TestCaseLoader.create_standard_suite()

# РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РІ РѕРїС‚РёРјРёР·Р°С†РёРё
result = await manager.run_optimization(
    version=OptimizerVersion.V1_PROMPT_ONLY,
    target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
    test_cases=test_cases
)
```

#### РЎРѕР·РґР°РЅРёРµ РєР°СЃС‚РѕРјРЅС‹С… С‚РµСЃС‚РѕРІ

```python
from app.optimizer import TestCase

custom_tests = [
    TestCase(
        id="custom_spanish_a2",
        description="Custom Spanish test",
        target_lang="Spanish",
        native_lang="English",
        cefr_level="A2",
        topic="Food",
        focus="vocabulary",
        expected_vocab_count=10,
        expected_dialogue_scenes=2,
        min_score=90
    ),
    # ... Р±РѕР»СЊС€Рµ С‚РµСЃС‚РѕРІ
]

# РЎРѕС…СЂР°РЅРёС‚СЊ РґР»СЏ РїРѕРІС‚РѕСЂРЅРѕРіРѕ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ
TestCaseLoader.save_test_suite(
    custom_tests,
    Path("my_custom_tests.json")
)
```

#### РСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ validation stress tests

```python
from app.services.optimizer.optimizer.testing import ValidationTestBuilder

# РЎРїРµС†РёР°Р»РёР·РёСЂРѕРІР°РЅРЅС‹Рµ С‚РµСЃС‚С‹ РґР»СЏ РІР°Р»РёРґР°С†РёРё
val_tests = ValidationTestBuilder.create_validation_stress_tests()

result = await manager.run_optimization(
    version=OptimizerVersion.V2_PROMPT_VALIDATION,
    target=OptimizationTarget.VALIDATION_RULES,
    test_cases=val_tests,
    optimize_validation=True
)
```

### РђРЅР°Р»РёР· СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ

#### РџСЂРѕСЃРјРѕС‚СЂ РѕС‚С‡РµС‚РѕРІ

РџРѕСЃР»Рµ РѕРїС‚РёРјРёР·Р°С†РёРё СЃРѕР·РґР°СЋС‚СЃСЏ РЅРµСЃРєРѕР»СЊРєРѕ РѕС‚С‡РµС‚РѕРІ:

1. **HTML РѕС‚С‡РµС‚** (`report.html`) - РёРЅС‚РµСЂР°РєС‚РёРІРЅС‹Р№ РїСЂРѕСЃРјРѕС‚СЂ
2. **Markdown РѕС‚С‡РµС‚** (`final_report.md`) - С‚РµРєСЃС‚РѕРІС‹Р№ С„РѕСЂРјР°С‚
3. **JSON РґР°РЅРЅС‹Рµ** (`final_report.json`) - РґР»СЏ РїСЂРѕРіСЂР°РјРјРЅРѕРіРѕ РґРѕСЃС‚СѓРїР°

```bash
# РћС‚РєСЂС‹С‚СЊ HTML РѕС‚С‡РµС‚
start optimizer_logs/v1/v1_prompt_content_creator_1234567890/report.html
```

#### РџСЂРѕРіСЂР°РјРјРЅС‹Р№ Р°РЅР°Р»РёР·

```python
from app.services.optimizer.optimizer.testing import TestResultAnalyzer

# РђРЅР°Р»РёР· СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ РѕРґРЅРѕР№ РёС‚РµСЂР°С†РёРё
analysis = TestResultAnalyzer.analyze_results(iteration.test_results)
print(analysis["summary"])
print(analysis["recommendations"])

# РЎСЂР°РІРЅРµРЅРёРµ РґРѕ/РїРѕСЃР»Рµ
comparison = TestResultAnalyzer.generate_comparison_report(
    before_results=iteration_1.test_results,
    after_results=iteration_5.test_results
)
print(comparison["verdict"])  # IMPROVED / STABLE / DEGRADED
```

### РЎСЂР°РІРЅРµРЅРёРµ РІРµСЂСЃРёР№

```bash
# Р§РµСЂРµР· CLI
python -m app.services.optimizer.optimizer.cli \
    --compare v1,v2 \
    --target prompt_content_creator \
    --iterations 3
```

```python
# Р§РµСЂРµР· API
results = await manager.compare_versions(
    versions=[
        OptimizerVersion.V1_PROMPT_ONLY,
        OptimizerVersion.V2_PROMPT_VALIDATION
    ],
    target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
    test_cases=test_cases,
    max_iterations=3
)

for version, result in results.items():
    print(f"{version}: {result.best_iteration.avg_score:.1f}/100")
```

### РЈРїСЂР°РІР»РµРЅРёРµ СЃРµСЃСЃРёСЏРјРё

```bash
# РџСЂРѕСЃРјРѕС‚СЂ РІСЃРµС… СЃРµСЃСЃРёР№
python -m app.services.optimizer.optimizer.cli --list-sessions

# РџСЂРѕСЃРјРѕС‚СЂ СЃРµСЃСЃРёР№ РєРѕРЅРєСЂРµС‚РЅРѕР№ РІРµСЂСЃРёРё
python -m app.services.optimizer.optimizer.cli --list-sessions --version v2
```

```python
# Р§РµСЂРµР· API
manager = OptimizerManager()

# РЎРїРёСЃРѕРє СЃРµСЃСЃРёР№
sessions = manager.list_sessions(version=OptimizerVersion.V2_PROMPT_VALIDATION)

# Р”РµС‚Р°Р»Рё СЃРµСЃСЃРёРё
for session_dir in sessions[:3]:
    summary = manager.get_session_summary(session_dir)
    print(f"Session: {session_dir.name}")
    print(f"Best score: {summary['best_iteration']['avg_score']:.1f}/100")
```

### Р’РѕР·РѕР±РЅРѕРІР»РµРЅРёРµ РѕРїС‚РёРјРёР·Р°С†РёРё

```bash
# CLI
python -m app.services.optimizer.optimizer.cli \
    --version v1 \
    --target prompt_content_creator \
    --resume
```

```python
# API
result = await manager.run_optimization(
    version=OptimizerVersion.V1_PROMPT_ONLY,
    target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
    resume=True
)
```

## рџ“– РџСЂРёРјРµСЂС‹

### РџСЂРёРјРµСЂ 1: Р‘Р°Р·РѕРІР°СЏ РѕРїС‚РёРјРёР·Р°С†РёСЏ РїСЂРѕРјРїС‚Р°

```python
import asyncio
from app.optimizer import optimize_prompt, OptimizationTarget

async def example_basic():
    # РЈРґРѕР±РЅР°СЏ С„СѓРЅРєС†РёСЏ РґР»СЏ Р±С‹СЃС‚СЂРѕР№ РѕРїС‚РёРјРёР·Р°С†РёРё
    result = await optimize_prompt(
        target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
        max_iterations=5
    )
    
    print(f"Optimization complete!")
    print(f"Initial: {result.iterations[0].avg_score:.1f}/100")
    print(f"Final: {result.iterations[-1].avg_score:.1f}/100")

asyncio.run(example_basic())
```

### РџСЂРёРјРµСЂ 2: РћРїС‚РёРјРёР·Р°С†РёСЏ С‚РѕР»СЊРєРѕ РІР°Р»РёРґР°С†РёРё

```python
from app.optimizer import optimize_validation

async def example_validation():
    result = await optimize_validation(max_iterations=5)
    
    # Р РµР·СѓР»СЊС‚Р°С‚ СЃРѕРґРµСЂР¶РёС‚ СѓР»СѓС‡С€РµРЅРЅС‹Рµ РїСЂР°РІРёР»Р° РІР°Р»РёРґР°С†РёРё
    best_rules = result.best_iteration.artifact["validation_rules"]
    
    print("Improved validation rules:")
    for rule_name, rule_config in best_rules.items():
        print(f"  {rule_name}: weight={rule_config['weight']}")

asyncio.run(example_validation())
```

### РџСЂРёРјРµСЂ 3: РЎРѕРІРјРµСЃС‚РЅР°СЏ РѕРїС‚РёРјРёР·Р°С†РёСЏ

```python
from app.optimizer import optimize_both

async def example_both():
    result = await optimize_both(max_iterations=10)
    
    # РџРѕР»СѓС‡Р°РµРј Р»СѓС‡С€РёРµ РІРµСЂСЃРёРё РѕР±РѕРёС… Р°СЂС‚РµС„Р°РєС‚РѕРІ
    best_artifact = result.best_iteration.artifact
    
    best_prompt = best_artifact.get("prompt")
    best_rules = best_artifact.get("validation_rules")
    
    print(f"Best iteration: {result.best_iteration.iteration}")
    print(f"Score: {result.best_iteration.avg_score:.1f}/100")

asyncio.run(example_both())
```

### РџСЂРёРјРµСЂ 4: РљР°СЃС‚РѕРјРЅР°СЏ РєРѕРЅС„РёРіСѓСЂР°С†РёСЏ

```python
from pathlib import Path
from app.optimizer import OptimizerManager, OptimizationTarget, OptimizerVersion
from app.services.optimizer.optimizer.testing import TestCaseLoader

async def example_custom():
    manager = OptimizerManager(
        base_output_dir=Path("my_experiments")
    )
    
    # Р—Р°РіСЂСѓР·РёС‚СЊ СЃРІРѕРё С‚РµСЃС‚С‹
    test_cases = TestCaseLoader.load_from_file(
        Path("my_test_cases.json")
    )
    
    # Р—Р°РїСѓСЃС‚РёС‚СЊ СЃ РєР°СЃС‚РѕРјРЅС‹РјРё РїР°СЂР°РјРµС‚СЂР°РјРё
    result = await manager.run_optimization(
        version=OptimizerVersion.V2_PROMPT_VALIDATION,
        target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
        test_cases=test_cases,
        max_iterations=15,
        stability_threshold=98.0,
        optimize_prompt=True,
        optimize_validation=True
    )
    
    return result

asyncio.run(example_custom())
```

## рџ”Ќ РЎС‚СЂСѓРєС‚СѓСЂР° СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ

РљР°Р¶РґР°СЏ СЃРµСЃСЃРёСЏ РѕРїС‚РёРјРёР·Р°С†РёРё СЃРѕР·РґР°РµС‚ СЃР»РµРґСѓСЋС‰СѓСЋ СЃС‚СЂСѓРєС‚СѓСЂСѓ:

```
optimizer_logs/v1/v1_prompt_content_creator_1234567890/
в”њв”Ђв”Ђ artifacts/              # РЎРѕС…СЂР°РЅРµРЅРЅС‹Рµ Р°СЂС‚РµС„Р°РєС‚С‹
в”‚   в”њв”Ђв”Ђ iteration_1/
в”‚   в”‚   в”њв”Ђв”Ђ prompt_85.txt
в”‚   в”‚   в””в”Ђв”Ђ validation_rules_85.json
в”‚   в””в”Ђв”Ђ iteration_2/
в”њв”Ђв”Ђ iteration_1/            # Р”РµС‚Р°Р»Рё РёС‚РµСЂР°С†РёРё
в”‚   в”њв”Ђв”Ђ results.json        # Р РµР·СѓР»СЊС‚Р°С‚С‹ С‚РµСЃС‚РѕРІ
в”‚   в”њв”Ђв”Ђ prompt.txt          # РСЃРїРѕР»СЊР·РѕРІР°РЅРЅС‹Р№ РїСЂРѕРјРїС‚
в”‚   в””в”Ђв”Ђ lessons/            # РЎРіРµРЅРµСЂРёСЂРѕРІР°РЅРЅС‹Рµ СѓСЂРѕРєРё
в”‚       в”њв”Ђв”Ђ test_1.json
в”‚       в””в”Ђв”Ђ test_1_raw.txt
в”њв”Ђв”Ђ final_report.json       # Р¤РёРЅР°Р»СЊРЅС‹Рµ РґР°РЅРЅС‹Рµ
в”њв”Ђв”Ђ final_report.md         # Markdown РѕС‚С‡РµС‚
в””в”Ђв”Ђ report.html             # РРЅС‚РµСЂР°РєС‚РёРІРЅС‹Р№ РѕС‚С‡РµС‚
```

## рџЋ“ Best Practices

### 1. РќР°С‡РЅРёС‚Рµ СЃ РјР°Р»РѕРіРѕ

```python
# РЎРЅР°С‡Р°Р»Р° РїСЂРѕС‚РµСЃС‚РёСЂСѓР№С‚Рµ РЅР° 3-5 РёС‚РµСЂР°С†РёСЏС…
result = await optimize_prompt(max_iterations=3)
```

### 2. РСЃРїРѕР»СЊР·СѓР№С‚Рµ РїРѕРґС…РѕРґСЏС‰РёРµ С‚РµСЃС‚С‹

```python
# Р”Р»СЏ РѕРїС‚РёРјРёР·Р°С†РёРё РІР°Р»РёРґР°С†РёРё РёСЃРїРѕР»СЊР·СѓР№С‚Рµ validation stress tests
from app.services.optimizer.optimizer.testing import ValidationTestBuilder

val_tests = ValidationTestBuilder.create_validation_stress_tests()
```

### 3. РњРѕРЅРёС‚РѕСЂСЊС‚Рµ РїСЂРѕРіСЂРµСЃСЃ

```python
# РџСЂРѕРІРµСЂСЏР№С‚Рµ РїСЂРѕРјРµР¶СѓС‚РѕС‡РЅС‹Рµ СЂРµР·СѓР»СЊС‚Р°С‚С‹
for iteration in result.iterations:
    print(f"Iteration {iteration.iteration}: {iteration.avg_score:.1f}/100")
```

### 4. РЎРѕС…СЂР°РЅСЏР№С‚Рµ Р»СѓС‡С€РёРµ СЂРµР·СѓР»СЊС‚Р°С‚С‹

```python
# Р›СѓС‡С€РёР№ Р°СЂС‚РµС„Р°РєС‚ РІСЃРµРіРґР° РґРѕСЃС‚СѓРїРµРЅ
best_prompt = result.best_iteration.artifact
```

### 5. РЎСЂР°РІРЅРёРІР°Р№С‚Рµ РїРѕРґС…РѕРґС‹

```bash
# Р РµРіСѓР»СЏСЂРЅРѕ СЃСЂР°РІРЅРёРІР°Р№С‚Рµ РІРµСЂСЃРёРё
python -m app.services.optimizer.optimizer.cli --compare v1,v2 --target prompt_content_creator
```

## рџђ› Troubleshooting

### РџСЂРѕР±Р»РµРјР°: РћРїС‚РёРјРёР·Р°С†РёСЏ РЅРµ СѓР»СѓС‡С€Р°РµС‚ СЂРµР·СѓР»СЊС‚Р°С‚С‹

**Р РµС€РµРЅРёРµ:**
- РЈРІРµР»РёС‡СЊС‚Рµ РєРѕР»РёС‡РµСЃС‚РІРѕ РёС‚РµСЂР°С†РёР№
- РџСЂРѕРІРµСЂСЊС‚Рµ РєР°С‡РµСЃС‚РІРѕ С‚РµСЃС‚РѕРІС‹С… СЃР»СѓС‡Р°РµРІ
- РСЃРїРѕР»СЊР·СѓР№С‚Рµ Р±РѕР»РµРµ СЂР°Р·РЅРѕРѕР±СЂР°Р·РЅС‹Рµ С‚РµСЃС‚С‹

### РџСЂРѕР±Р»РµРјР°: РЎР»РёС€РєРѕРј РґРѕР»РіРѕ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ

**Р РµС€РµРЅРёРµ:**
- РЈРјРµРЅСЊС€РёС‚Рµ РєРѕР»РёС‡РµСЃС‚РІРѕ С‚РµСЃС‚РѕРІС‹С… СЃР»СѓС‡Р°РµРІ
- РСЃРїРѕР»СЊР·СѓР№С‚Рµ Р±РѕР»РµРµ Р±С‹СЃС‚СЂС‹Рµ РјРѕРґРµР»Рё
- Р—Р°РїСѓСЃРєР°Р№С‚Рµ РЅР° РјРµРЅСЊС€РµРј РєРѕР»РёС‡РµСЃС‚РІРµ РёС‚РµСЂР°С†РёР№

### РџСЂРѕР±Р»РµРјР°: Р’С‹СЃРѕРєР°СЏ РІР°СЂРёР°С‚РёРІРЅРѕСЃС‚СЊ СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ

**Р РµС€РµРЅРёРµ:**
- РСЃРїРѕР»СЊР·СѓР№С‚Рµ Р±РѕР»СЊС€Рµ С‚РµСЃС‚РѕРІС‹С… СЃР»СѓС‡Р°РµРІ
- РЈРІРµР»РёС‡СЊС‚Рµ stability_threshold
- Р”РѕР±Р°РІСЊС‚Рµ Р±РѕР»СЊС€Рµ edge cases РІ С‚РµСЃС‚С‹

## рџ“ќ TODO / Roadmap

- [ ] V3 optimizer СЃ multi-target РѕРїС‚РёРјРёР·Р°С†РёРµР№
- [ ] РџРѕРґРґРµСЂР¶РєР° A/B С‚РµСЃС‚РёСЂРѕРІР°РЅРёСЏ
- [ ] РРЅС‚РµРіСЂР°С†РёСЏ СЃ CI/CD
- [ ] Web UI РґР»СЏ РїСЂРѕСЃРјРѕС‚СЂР° СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ
- [ ] РђРІС‚РѕРјР°С‚РёС‡РµСЃРєРёРµ Р°Р»РµСЂС‚С‹ РїСЂРё РґРµРіСЂР°РґР°С†РёРё
- [ ] Р­РєСЃРїРѕСЂС‚ Р»СѓС‡С€РёС… Р°СЂС‚РµС„Р°РєС‚РѕРІ РІ РїСЂРѕРґР°РєС€РЅ

## рџ“„ Р›РёС†РµРЅР·РёСЏ

Р§Р°СЃС‚СЊ РїСЂРѕРµРєС‚Р° seed.server.v5

