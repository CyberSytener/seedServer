# Migration Guide: optimizer_mode.py в†’ New Optimizer System

Р­С‚Рѕ СЂСѓРєРѕРІРѕРґСЃС‚РІРѕ РїРѕРјРѕР¶РµС‚ РІР°Рј РїРµСЂРµР№С‚Рё СЃ СѓСЃС‚Р°СЂРµРІС€РµРіРѕ `optimizer_mode.py` РЅР° РЅРѕРІСѓСЋ СЃРёСЃС‚РµРјСѓ СЃ РІРµСЂСЃРёРѕРЅРёСЂРѕРІР°РЅРёРµРј.

## рџ”„ Р§С‚Рѕ РёР·РјРµРЅРёР»РѕСЃСЊ

### РЎС‚Р°СЂС‹Р№ РїРѕРґС…РѕРґ (optimizer_mode.py)

```python
# РћРґРёРЅ РјРѕРЅРѕР»РёС‚РЅС‹Р№ С„Р°Р№Р»
# РћРїС‚РёРјРёР·Р°С†РёСЏ С‚РѕР»СЊРєРѕ РїСЂРѕРјРїС‚РѕРІ
# РќРµС‚ РІРµСЂСЃРёРѕРЅРёСЂРѕРІР°РЅРёСЏ
# Р РµР·СѓР»СЊС‚Р°С‚С‹ РїРµСЂРµР·Р°РїРёСЃС‹РІР°СЋС‚СЃСЏ

from app.optimizer_mode import run_optimization

result = await run_optimization(
    max_iterations=5,
    resume=False
)
```

### РќРѕРІС‹Р№ РїРѕРґС…РѕРґ (app/optimizer/)

```python
# РњРѕРґСѓР»СЊРЅР°СЏ Р°СЂС…РёС‚РµРєС‚СѓСЂР°
# РћРїС‚РёРјРёР·Р°С†РёСЏ РїСЂРѕРјРїС‚РѕРІ, РІР°Р»РёРґР°С†РёРё, Рё РїР°СЂР°РјРµС‚СЂРѕРІ
# РњРЅРѕР¶РµСЃС‚РІРµРЅРЅС‹Рµ РІРµСЂСЃРёРё РѕРїС‚РёРјРёР·Р°С‚РѕСЂРѕРІ
# Р’СЃРµ СЂРµР·СѓР»СЊС‚Р°С‚С‹ СЃРѕС…СЂР°РЅСЏСЋС‚СЃСЏ

from app.optimizer import OptimizerManager, OptimizerVersion, OptimizationTarget

manager = OptimizerManager()
result = await manager.run_optimization(
    version=OptimizerVersion.V1_PROMPT_ONLY,  # РђРЅР°Р»РѕРі СЃС‚Р°СЂРѕРіРѕ optimizer_mode
    target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
    max_iterations=5
)
```

## рџ“‹ РњРёРіСЂР°С†РёСЏ РєРѕРґР°

### Р‘Р°Р·РѕРІР°СЏ РѕРїС‚РёРјРёР·Р°С†РёСЏ РїСЂРѕРјРїС‚Р°

**Р”Рѕ:**
```python
from app.optimizer_mode import run_optimization

async def optimize():
    result = await run_optimization(
        max_iterations=10,
        resume=False,
        test_cases_file="test_cases.json"
    )
    return result
```

**РџРѕСЃР»Рµ:**
```python
from app.optimizer import optimize_prompt, OptimizationTarget
from pathlib import Path

async def optimize():
    result = await optimize_prompt(
        target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
        max_iterations=10,
        test_cases_file=Path("test_cases.json")
    )
    return result
```

### РСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ РєР°СЃС‚РѕРјРЅС‹С… С‚РµСЃС‚РѕРІ

**Р”Рѕ:**
```python
# test_cases.json С‚СЂРµР±РѕРІР°Р»СЃСЏ РІСЃРµРіРґР°
result = await run_optimization(test_cases_file="test_cases.json")
```

**РџРѕСЃР»Рµ:**
```python
# РњРѕР¶РЅРѕ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ СЃС‚Р°РЅРґР°СЂС‚РЅС‹Р№ РЅР°Р±РѕСЂ РёР»Рё РєР°СЃС‚РѕРјРЅС‹Р№
from app.optimizer import OptimizerManager, TestCaseLoader
from pathlib import Path

manager = OptimizerManager()

# Р’Р°СЂРёР°РЅС‚ 1: РЎС‚Р°РЅРґР°СЂС‚РЅС‹Рµ С‚РµСЃС‚С‹ (Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё)
result = await manager.run_optimization(
    version=OptimizerVersion.V1_PROMPT_ONLY,
    target=OptimizationTarget.PROMPT_CONTENT_CREATOR
)

# Р’Р°СЂРёР°РЅС‚ 2: Р—Р°РіСЂСѓР·РёС‚СЊ РёР· С„Р°Р№Р»Р°
test_cases = TestCaseLoader.load_from_file(Path("test_cases.json"))
result = await manager.run_optimization(
    version=OptimizerVersion.V1_PROMPT_ONLY,
    target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
    test_cases=test_cases
)

# Р’Р°СЂРёР°РЅС‚ 3: РЎРѕР·РґР°С‚СЊ РїСЂРѕРіСЂР°РјРјРЅРѕ
from app.optimizer import TestCase

custom_tests = [
    TestCase(
        id="my_test",
        description="Custom test",
        target_lang="Spanish",
        native_lang="English",
        cefr_level="A2",
        topic="Food",
        focus="vocabulary",
        expected_vocab_count=10,
        expected_dialogue_scenes=2,
        min_score=90
    )
]
result = await manager.run_optimization(
    version=OptimizerVersion.V1_PROMPT_ONLY,
    target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
    test_cases=custom_tests
)
```

### Р’РѕР·РѕР±РЅРѕРІР»РµРЅРёРµ РѕРїС‚РёРјРёР·Р°С†РёРё

**Р”Рѕ:**
```python
result = await run_optimization(resume=True)
```

**РџРѕСЃР»Рµ:**
```python
result = await manager.run_optimization(
    version=OptimizerVersion.V1_PROMPT_ONLY,
    target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
    resume=True
)
```

### Р”РѕСЃС‚СѓРї Рє СЂРµР·СѓР»СЊС‚Р°С‚Р°Рј

**Р”Рѕ:**
```python
# Р РµР·СѓР»СЊС‚Р°С‚С‹ РІ optimizer_logs/
# РћРґРёРЅ С„Р°Р№Р» optimization_report.md

result = await run_optimization()
best_prompt = result.best_iteration.prompt_text
```

**РџРѕСЃР»Рµ:**
```python
# Р РµР·СѓР»СЊС‚Р°С‚С‹ РІ optimizer_logs/v1/ РёР»Рё optimizer_logs/v2/
# РљР°Р¶РґР°СЏ СЃРµСЃСЃРёСЏ РІ РѕС‚РґРµР»СЊРЅРѕР№ РїР°РїРєРµ
# РњРЅРѕР¶РµСЃС‚РІРµРЅРЅС‹Рµ С„РѕСЂРјР°С‚С‹ РѕС‚С‡РµС‚РѕРІ (HTML, Markdown, JSON)

result = await manager.run_optimization(...)

# Р”РѕСЃС‚СѓРї Рє Р»СѓС‡С€РµРјСѓ РїСЂРѕРјРїС‚Сѓ
if isinstance(result.best_iteration.artifact, str):
    best_prompt = result.best_iteration.artifact
elif isinstance(result.best_iteration.artifact, dict):
    best_prompt = result.best_iteration.artifact.get("prompt")

# Р”РѕСЃС‚СѓРї Рє СЃРµСЃСЃРёРё
print(f"Session directory: {manager.get_optimizer(...).session_dir}")
```

## рџ†• РќРѕРІС‹Рµ РІРѕР·РјРѕР¶РЅРѕСЃС‚Рё

### 1. РћРїС‚РёРјРёР·Р°С†РёСЏ РІР°Р»РёРґР°С†РёРё

РўРµРїРµСЂСЊ РјРѕР¶РЅРѕ РѕРїС‚РёРјРёР·РёСЂРѕРІР°С‚СЊ РЅРµ С‚РѕР»СЊРєРѕ РїСЂРѕРјРїС‚С‹, РЅРѕ Рё РїСЂР°РІРёР»Р° РІР°Р»РёРґР°С†РёРё:

```python
from app.optimizer import optimize_validation

# РћРїС‚РёРјРёР·Р°С†РёСЏ С‚РѕР»СЊРєРѕ РІР°Р»РёРґР°С†РёРё
result = await optimize_validation(max_iterations=5)

# Р”РѕСЃС‚СѓРї Рє СѓР»СѓС‡С€РµРЅРЅС‹Рј РїСЂР°РІРёР»Р°Рј
best_rules = result.best_iteration.artifact["validation_rules"]
```

### 2. РљРѕРјР±РёРЅРёСЂРѕРІР°РЅРЅР°СЏ РѕРїС‚РёРјРёР·Р°С†РёСЏ

РћРїС‚РёРјРёР·Р°С†РёСЏ РїСЂРѕРјРїС‚РѕРІ Рё РІР°Р»РёРґР°С†РёРё РѕРґРЅРѕРІСЂРµРјРµРЅРЅРѕ:

```python
from app.optimizer import optimize_both

result = await optimize_both(max_iterations=10)

# РћР±Р° Р°СЂС‚РµС„Р°РєС‚Р° РґРѕСЃС‚СѓРїРЅС‹
best_prompt = result.best_iteration.artifact["prompt"]
best_rules = result.best_iteration.artifact["validation_rules"]
```

### 3. РЎСЂР°РІРЅРµРЅРёРµ РІРµСЂСЃРёР№

```python
results = await manager.compare_versions(
    versions=[
        OptimizerVersion.V1_PROMPT_ONLY,
        OptimizerVersion.V2_PROMPT_VALIDATION
    ],
    target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
    test_cases=test_cases
)

# РЎСЂР°РІРЅРµРЅРёРµ СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ
for version, result in results.items():
    print(f"{version}: {result.best_iteration.avg_score:.1f}/100")
```

### 4. CLI РёРЅС‚РµСЂС„РµР№СЃ

```bash
# Р§РµСЂРµР· РєРѕРјР°РЅРґРЅСѓСЋ СЃС‚СЂРѕРєСѓ (СЂР°РЅСЊС€Рµ РЅРµ Р±С‹Р»Рѕ)
python -m app.services.optimizer.optimizer.cli \
    --version v1 \
    --target prompt_content_creator \
    --iterations 5

# РЎСЂР°РІРЅРµРЅРёРµ РІРµСЂСЃРёР№
python -m app.services.optimizer.optimizer.cli \
    --compare v1,v2 \
    --target prompt_content_creator

# РџСЂРѕСЃРјРѕС‚СЂ СЃРµСЃСЃРёР№
python -m app.services.optimizer.optimizer.cli --list-sessions
```

## рџ“‚ РЎС‚СЂСѓРєС‚СѓСЂР° С„Р°Р№Р»РѕРІ

### Р”Рѕ

```
seed_server/
в”њв”Ђв”Ђ app/
в”‚   в””в”Ђв”Ђ optimizer_mode.py          # Р’РµСЃСЊ РєРѕРґ РІ РѕРґРЅРѕРј С„Р°Р№Р»Рµ
в”њв”Ђв”Ђ optimizer_logs/
в”‚   в””в”Ђв”Ђ session_20240114_123456/   # РћРґРЅР° СЃС‚СЂСѓРєС‚СѓСЂР°
в””в”Ђв”Ђ optimization_report.md
```

### РџРѕСЃР»Рµ

```
seed_server/
в”њв”Ђв”Ђ app/
в”‚   в””в”Ђв”Ђ optimizer/                 # РњРѕРґСѓР»СЊРЅР°СЏ Р°СЂС…РёС‚РµРєС‚СѓСЂР°
в”‚       в”њв”Ђв”Ђ __init__.py
в”‚       в”њв”Ђв”Ђ base.py                # Р‘Р°Р·РѕРІС‹Рµ РєР»Р°СЃСЃС‹
в”‚       в”њв”Ђв”Ђ optimizer_v1.py        # V1 РѕРїС‚РёРјРёР·Р°С‚РѕСЂ
в”‚       в”њв”Ђв”Ђ optimizer_v2.py        # V2 РѕРїС‚РёРјРёР·Р°С‚РѕСЂ
в”‚       в”њв”Ђв”Ђ manager.py             # РњРµРЅРµРґР¶РµСЂ
в”‚       в”њв”Ђв”Ђ testing.py             # РўРµСЃС‚РѕРІР°СЏ РёРЅС„СЂР°СЃС‚СЂСѓРєС‚СѓСЂР°
в”‚       в”њв”Ђв”Ђ cli.py                 # CLI РёРЅС‚РµСЂС„РµР№СЃ
в”‚       в””в”Ђв”Ђ README.md              # Р”РѕРєСѓРјРµРЅС‚Р°С†РёСЏ
в”њв”Ђв”Ђ optimizer_logs/
в”‚   в”њв”Ђв”Ђ v1/                        # Р РµР·СѓР»СЊС‚Р°С‚С‹ V1
в”‚   в”‚   в””в”Ђв”Ђ v1_prompt_content_creator_1234567890/
в”‚   в”‚       в”њв”Ђв”Ђ prompts/
в”‚   в”‚       в”њв”Ђв”Ђ iteration_1/
в”‚   в”‚       в”њв”Ђв”Ђ final_report.json
в”‚   в”‚       в”њв”Ђв”Ђ final_report.md
в”‚   в”‚       в””в”Ђв”Ђ report.html
в”‚   в”њв”Ђв”Ђ v2/                        # Р РµР·СѓР»СЊС‚Р°С‚С‹ V2
в”‚   в””в”Ђв”Ђ comparisons/               # РЎСЂР°РІРЅРµРЅРёСЏ РІРµСЂСЃРёР№
в””в”Ђв”Ђ example_optimizer.py           # РџСЂРёРјРµСЂС‹ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ
```

## вљ пёЏ Breaking Changes

### 1. РРјРїРѕСЂС‚С‹

**Р”Рѕ:**
```python
from app.optimizer_mode import run_optimization, optimize_system_prompt
```

**РџРѕСЃР»Рµ:**
```python
from app.optimizer import (
    OptimizerManager,
    optimize_prompt,
    optimize_validation,
    optimize_both
)
```

### 2. РЎС‚СЂСѓРєС‚СѓСЂР° СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ

**Р”Рѕ:**
```python
result.prompt_versions  # List[PromptVersion]
result.best_iteration.prompt_text  # str
```

**РџРѕСЃР»Рµ:**
```python
result.iterations  # List[OptimizationIteration]
result.best_iteration.artifact  # Union[str, Dict[str, Any]]

# Р”Р»СЏ РїСЂРѕРјРїС‚Р°
if isinstance(result.best_iteration.artifact, str):
    prompt = result.best_iteration.artifact
else:
    prompt = result.best_iteration.artifact.get("prompt")
```

### 3. РџСѓС‚Рё Рє С„Р°Р№Р»Р°Рј

**Р”Рѕ:**
```python
# Р РµР·СѓР»СЊС‚Р°С‚С‹ РІ РєРѕСЂРЅРµ optimizer_logs/
optimizer_logs/session_*/
```

**РџРѕСЃР»Рµ:**
```python
# Р РµР·СѓР»СЊС‚Р°С‚С‹ РІ РїРѕРґРґРёСЂРµРєС‚РѕСЂРёСЏС… РїРѕ РІРµСЂСЃРёСЏРј
optimizer_logs/v1/session_*/
optimizer_logs/v2/session_*/
```

## рџ”§ РћР±СЂР°С‚РЅР°СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ

РЎС‚Р°СЂС‹Р№ `optimizer_mode.py` **РѕСЃС‚Р°РµС‚СЃСЏ** РІ РїСЂРѕРµРєС‚Рµ РґР»СЏ РѕР±СЂР°С‚РЅРѕР№ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё, РЅРѕ РїРѕРјРµС‡РµРЅ РєР°Рє deprecated.

Р•СЃР»Рё РІР°Рј РЅСѓР¶РЅРѕ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ СЃС‚Р°СЂС‹Р№ РєРѕРґ:

```python
# Р’СЃРµ РµС‰Рµ СЂР°Р±РѕС‚Р°РµС‚, РЅРѕ deprecated
from app.optimizer_mode import run_optimization

result = await run_optimization(max_iterations=5)
```

вљ пёЏ **Р РµРєРѕРјРµРЅРґР°С†РёСЏ:** РњРёРіСЂРёСЂСѓР№С‚Рµ РЅР° РЅРѕРІСѓСЋ СЃРёСЃС‚РµРјСѓ РґР»СЏ РґРѕСЃС‚СѓРїР° Рє РЅРѕРІС‹Рј РІРѕР·РјРѕР¶РЅРѕСЃС‚СЏРј.

## рџ“ќ Checklist РјРёРіСЂР°С†РёРё

- [ ] РћР±РЅРѕРІРёС‚СЊ РёРјРїРѕСЂС‚С‹ СЃ `app.optimizer_mode` РЅР° `app.optimizer`
- [ ] Р—Р°РјРµРЅРёС‚СЊ `run_optimization()` РЅР° `OptimizerManager().run_optimization()`
- [ ] РЈРєР°Р·Р°С‚СЊ РІРµСЂСЃРёСЋ РѕРїС‚РёРјРёР·Р°С‚РѕСЂР° (V1 РґР»СЏ Р°РЅР°Р»РѕРіР° СЃС‚Р°СЂРѕРіРѕ РїРѕРІРµРґРµРЅРёСЏ)
- [ ] РЈРєР°Р·Р°С‚СЊ С†РµР»СЊ РѕРїС‚РёРјРёР·Р°С†РёРё (target)
- [ ] РћР±РЅРѕРІРёС‚СЊ РїСѓС‚Рё Рє СЂРµР·СѓР»СЊС‚Р°С‚Р°Рј (РґРѕР±Р°РІРёС‚СЊ v1/ РёР»Рё v2/)
- [ ] РћР±РЅРѕРІРёС‚СЊ РєРѕРґ РґРѕСЃС‚СѓРїР° Рє Р°СЂС‚РµС„Р°РєС‚Р°Рј (artifact РІРјРµСЃС‚Рѕ prompt_text)
- [ ] РџСЂРѕС‚РµСЃС‚РёСЂРѕРІР°С‚СЊ РјРёРіСЂР°С†РёСЋ РЅР° РЅРµР±РѕР»СЊС€РёС… РґР°РЅРЅС‹С…

## рџЋ“ Р РµРєРѕРјРµРЅРґР°С†РёРё

1. **РќР°С‡РЅРёС‚Рµ СЃ V1** РµСЃР»Рё РІР°Рј РЅСѓР¶РЅР° С‚РѕР»СЊРєРѕ РѕРїС‚РёРјРёР·Р°С†РёСЏ РїСЂРѕРјРїС‚РѕРІ
2. **РСЃРїРѕР»СЊР·СѓР№С‚Рµ V2** РµСЃР»Рё С…РѕС‚РёС‚Рµ РѕРїС‚РёРјРёР·РёСЂРѕРІР°С‚СЊ РІР°Р»РёРґР°С†РёСЋ
3. **РСЃРїРѕР»СЊР·СѓР№С‚Рµ convenience functions** (`optimize_prompt`, `optimize_validation`, `optimize_both`) РґР»СЏ РїСЂРѕСЃС‚С‹С… СЃР»СѓС‡Р°РµРІ
4. **РСЃРїРѕР»СЊР·СѓР№С‚Рµ OptimizerManager** РґР»СЏ РїРѕР»РЅРѕРіРѕ РєРѕРЅС‚СЂРѕР»СЏ

## рџ† РџРѕР»СѓС‡РёС‚СЊ РїРѕРјРѕС‰СЊ

Р•СЃР»Рё РІРѕР·РЅРёРєР»Рё РІРѕРїСЂРѕСЃС‹ РїСЂРё РјРёРіСЂР°С†РёРё:

1. РР·СѓС‡РёС‚Рµ [README.md](README.md) РІ РґРёСЂРµРєС‚РѕСЂРёРё optimizer/
2. Р—Р°РїСѓСЃС‚РёС‚Рµ [example_optimizer.py](../../example_optimizer.py)
3. РџСЂРѕРІРµСЂСЊС‚Рµ CLI РїРѕРјРѕС‰СЊ: `python -m app.services.optimizer.optimizer.cli --help`

## рџ“љ Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Рµ СЂРµСЃСѓСЂСЃС‹

- [Optimizer README](README.md) - РџРѕР»РЅР°СЏ РґРѕРєСѓРјРµРЅС‚Р°С†РёСЏ
- [example_optimizer.py](../../example_optimizer.py) - РџСЂРёРјРµСЂС‹ РєРѕРґР°
- CLI: `python -m app.services.optimizer.optimizer.cli --help` - РЎРїСЂР°РІРєР° РїРѕ РєРѕРјР°РЅРґРЅРѕР№ СЃС‚СЂРѕРєРµ

