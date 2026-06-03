# Test Prompts Archive

This directory contains archived versions of test prompts for A/B testing and optimization tracking.

## Purpose

- **Backup:** Preserve previous versions before improvements
- **Rollback:** Quick restore if new version causes issues  
- **Analysis:** Compare multiple versions over time
- **Documentation:** Track what changed and why

## Naming Convention

```
{prompt_name}_v{version}_{timestamp}.md
```

**Example:**
```
diagnostic_generator_v1_20260111_045607.md
```

- `diagnostic_generator` - Prompt name
- `v1` - Version number
- `20260111_045607` - Timestamp (YYYYMMDD_HHMMSS)

## Archive Process

### Manual Archiving
```powershell
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item "prompts\test\diagnostic_generator.md" "prompts\test\archive\diagnostic_generator_v2_$timestamp.md"
```

### Automated (Future)
Add to deployment pipeline:
```bash
# Before updating test prompt
./scripts/archive_prompt.sh diagnostic_generator
```

## Version History

### diagnostic_generator

| Version | Date | Changes | Performance | Status |
|---------|------|---------|-------------|--------|
| v1 | 2026-01-11 03:30 | Initial compact format (41 lines) | +14% slower | Archived |
| v2 | 2026-01-11 04:56 | Added validation checklist (54 lines) | -9% faster | **Active** |

**v1 → v2 Changes:**
- ✅ Added explicit validation checklist
- ✅ Clarified task-specific requirements  
- ✅ Added descriptive ID format guideline
- ✅ Emphasized critical constraints (answer.accepted never empty)

**Results:**
- Token reduction: 46% (2800 → 1500)
- Speed improvement: 9% faster
- Quality: Zero errors maintained

---

## Best Practices

### Before Creating New Version
1. ✅ Archive current version with timestamp
2. ✅ Document changes in version history table
3. ✅ Run A/B test (baseline vs new version)
4. ✅ Analyze quality metrics (errors, warnings, variety)
5. ✅ Update version number in prompt header

### Testing New Versions
```python
# Set test mode
SEED_PROMPT_TEST_MODE=true

# Run comparison
python compare_prompts_v2.py

# Analyze quality
python comprehensive_analysis.py
```

### Rollback Procedure
```powershell
# Copy archived version back to active
Copy-Item "archive\diagnostic_generator_v1_20260111_045607.md" "..\diagnostic_generator.md"

# Rebuild Docker
docker-compose up -d --build api
```

---

## File Structure

```
prompts/
├── diagnostic_generator.md          # Baseline (production)
├── lesson_generator.md
├── test/
│   ├── diagnostic_generator.md      # Test version (v2 active)
│   ├── lesson_generator.md
│   └── archive/                     # 👈 You are here
│       ├── diagnostic_generator_v1_20260111_045607.md
│       └── ...future versions
```

---

## Monitoring

Track metrics for each version:
- **Generation time** (avg, p50, p95)
- **Token usage** (input + output)
- **Error rate** (validation failures)
- **Quality score** (task variety + CEFR spread)

See [PROMPT_OPTIMIZATION_REPORT.md](../../../PROMPT_OPTIMIZATION_REPORT.md) for full analysis.

---

**Last Updated:** 2026-01-11  
**Maintained by:** Development Team
