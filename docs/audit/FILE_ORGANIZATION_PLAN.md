# Структурный Аудит - Файлы для Организации

## ДОКУМЕНТАЦИЯ (25+ файлов в ROOT)

### Архитектура и реализация
- SCALABILITY_UX_IMPROVEMENTS.md → docs/features/async-streaming.md
- ASYNC_LLM_README.md → docs/features/async-llm.md
- DIAGNOSTIC_V0.md → docs/features/diagnostic-v0.md
- DIAGNOSTIC_V0_QUICK_REF.md → docs/quick-refs/diagnostic.md
- LEARNING_PATH_IMPLEMENTATION_SUMMARY.md → docs/features/learning-paths.md
- ADAPTIVE_LEARNING_RU.md → docs/guides/adaptive-learning-ru.md
- LEARNING_PROFILE_IMPLEMENTATION.md → docs/features/learning-profiles.md
- LEARNING_PROFILE_API_REFERENCE.md → docs/api/learning-profiles.md

### Безопасность и инфраструктура
- API_KEY_MANAGEMENT.md → docs/security/api-keys.md
- SECURITY_IMPROVEMENTS_REPORT.md → docs/security/improvements.md
- SECRET_MANAGEMENT.md → docs/security/secrets.md
- SECRET_MANAGEMENT_COMPLETE.md → docs/security/secrets-complete.md
- SECRET_MANAGEMENT_QUICKREF.md → docs/quick-refs/secrets.md
- AUTH_SECURITY_PATCHES.md → docs/security/auth-patches.md
- LLM_TRUST_BOUNDARY.md → docs/security/llm-trust-boundary.md
- LLM_TRUST_BOUNDARY_SUMMARY.md → docs/security/llm-trust-summary.md

### Personas и контент
- PERSONA_IMPLEMENTATION.md → docs/features/personas.md

### QA и тестирование
- QA_PERSONA_REPORT.md → docs/quality/persona-qa.md
- BUG_REPORTS_IMPLEMENTATION.md → docs/features/bug-reports.md
- BUG_REPORT_COMPAT.md → docs/quality/bug-reports-compat.md
- TEST_HERMITICITY_REPORT.md → docs/quality/test-hermiticity.md
- TEST_INFRASTRUCTURE_COMPLETE.md → docs/quality/test-infrastructure.md
- TEST_INFRASTRUCTURE_QUICKREF.md → docs/quick-refs/testing.md
- TESTING_WITHOUT_DEPENDENCIES.md → docs/guides/testing-offline.md

### Monitoring и deployment
- SLO_MONITORING_IMPLEMENTATION.md → docs/operations/slo-monitoring.md
- SLO_QUICKREF.md → docs/quick-refs/slo.md
- PROMPT_TESTING_IMPLEMENTATION_REPORT.md → docs/features/prompt-testing.md
- PROMPT_TESTING_SYSTEM.md → docs/guides/prompt-testing-guide.md
- PROMPT_OPTIMIZATION_REPORT.md → docs/quality/prompt-optimization.md

### Deployment и миграция
- DEPLOYMENT_GUIDE.md → docs/operations/deployment.md
- MIGRATION_CHECKLIST.md → docs/operations/migration.md
- PRODUCTION_DEPLOYMENT_SUMMARY.md → docs/operations/deployment-summary.md
- PRODUCTION_MIGRATION_REPORT.md → docs/operations/migration-report.md
- PRODUCTION_READINESS_SUMMARY.md → docs/operations/readiness.md
- CRITICAL_IMPROVEMENTS_COMPLETE.md → docs/operations/critical-improvements.md
- KEY_IMPROVEMENTS_COMPLETE.md → docs/operations/key-improvements.md

### Client и compatibility
- CLIENT_V1_COMPLETE.md → docs/api/client-v1.md
- CLIENT_V1_IMPLEMENTATION.md → docs/api/client-v1-impl.md
- DESKTOP_CLIENT_AUTH_FIX.md → docs/guides/desktop-client-auth.md

### Diagnostics специфичные
- DIAGNOSTIC_ITEMS.md → docs/features/diagnostic-items.md
- DIAGNOSTIC_PERFORMANCE.md → docs/quality/diagnostic-performance.md
- DIAGNOSTIC_FIX_REPORT.md → docs/quality/diagnostic-fixes.md
- DIAGNOSTIC_404_TROUBLESHOOTING.md → docs/troubleshooting/diagnostic-404.md
- DIAGNOSTIC_VERIFICATION_COMPLETE.md → docs/quality/diagnostic-verification.md
- HOTFIX_DIAGNOSTIC_VALIDATION.md → docs/hotfixes/diagnostic-validation.md
- HOTFIX_FILL_BLANK_TASK.md → docs/hotfixes/fill-blank-task.md
- HOTFIX_LESSON_GENERATION_AUTH.md → docs/hotfixes/lesson-generation-auth.md
- HOTFIX_TRANSLATE_TASK.md → docs/hotfixes/translate-task.md

### CORS и конфигурация
- CORS_MULTI_PORT.md → docs/operations/cors-multi-port.md
- CORS_VERIFICATION.md → docs/operations/cors-verification.md

### CI/Security
- CI_SECURITY_GUIDE.md → docs/operations/ci-security.md
- CI_SECURITY_README.md → docs/operations/ci-security-readme.md
- CI_SECURITY_SUMMARY.md → docs/operations/ci-security-summary.md

### JSON Logging и другое
- JSON_LOGGING_IMPLEMENTATION.md → docs/operations/json-logging.md
- LESSON_THREAD_ENDPOINTS.md → docs/api/lesson-threads.md
- LESSON_TRANSLATE_VALIDATION.md → docs/quality/lesson-translate.md
- LESSON_VALIDATION_TESTS.md → docs/quality/lesson-validation.md
- LEARNING_PATH_ANALYTICS.md → docs/features/path-analytics.md
- LEARNING_PATH_API.md → docs/api/learning-paths-api.md
- QUICK_REFERENCE_ASYNC.md → docs/quick-refs/async.md
- IMPLEMENTATION_SUMMARY.md → docs/operations/implementation-summary.md
- REPORT.md → docs/reports/summary.md

---

## ТЕСТОВЫЕ СКРИПТЫ (20+ файлов в ROOT)

### Диагностики и проверки (15 файлов)
```
check_analytics.py              → scripts/diagnostics/check_analytics.py
check_bug_reports.py            → scripts/diagnostics/check_bug_reports.py
check_bug_reports_table.py      → scripts/diagnostics/check_bug_reports_table.py
check_desktop_profile.py        → scripts/diagnostics/check_desktop_profile.py
check_diagnostic_data.py        → scripts/diagnostics/check_diagnostic_data.py
check_diagnostic_profiles.py    → scripts/diagnostics/check_diagnostic_profiles.py
check_imports.py                → scripts/diagnostics/check_imports.py
check_learning_profiles.py      → scripts/diagnostics/check_learning_profiles.py
check_production_ready.py        → scripts/diagnostics/check_production_ready.py
check_profiles.py               → scripts/diagnostics/check_profiles.py
check_real_sessions.py          → scripts/diagnostics/check_real_sessions.py
check_schema.py                 → scripts/diagnostics/check_schema.py

analyze_diagnostic_quality.py   → scripts/analysis/analyze_diagnostic_quality.py
comprehensive_analysis.py       → scripts/analysis/comprehensive_analysis.py
debug_cefr.py                   → scripts/analysis/debug_cefr.py
```

### Verification и monitoring
```
verify_ci_security.py           → scripts/verify/verify_ci_security.py
verify_llm_trust_boundary.py    → scripts/verify/verify_llm_trust_boundary.py
verify_secret_management.py     → scripts/verify/verify_secret_management.py
verify_slo_monitoring.py        → scripts/verify/verify_slo_monitoring.py
verify_test_infrastructure.py   → scripts/verify/verify_test_infrastructure.py
verify_test_hermiticity.py      → scripts/verify/verify_test_hermiticity.py
```

### Setup и utilities
```
setup_monitoring.py             → scripts/setup/setup_monitoring.py
docker_extract.py               → scripts/utils/docker_extract.py
extract_items_from_db.py        → scripts/utils/extract_items_from_db.py
```

### Примеры для клиента
```
example_adaptive_client.py       → examples/clients/adaptive_client.py
example_async_client.py          → examples/clients/async_client.py
```

---

## UNIT ТЕСТЫ (20+ файлов в ROOT)

### Диагностика
```
test_diagnostic.py
test_diagnostic_async.py
test_diagnostic_async_auto.py
test_diagnostic_request.json
```
→ tests/unit/diagnostic/

### Learning Paths и Profiles
```
test_learning_path_simple.py
test_path_analytics.py
test_path_integration.py
test_path_models.py
```
→ tests/unit/learning_path/

### Endpoints и APIs
```
test_async_endpoints.py
test_end_to_end_flow.py
test_streaming_comprehensive.py
test_prompt_system.py
test_llm_validator.py
```
→ tests/integration/endpoints/

### Placement tests
```
test_placement_async_final.py
test_placement_eng_spanish.py
test_placement_proof.py
test_placement_simple.py
```
→ tests/integration/placement/

### Specialized tests
```
test_specialized_comprehensive.py
test_specialized_content.py
test_specialized_quick.py
```
→ tests/specialized/

### Bug reports
```
test_bug_report.py
test_bug_report_compat.py
```
→ tests/unit/bug_reports/

---

## JSON ДАННЫЕ (12+ файлов)

### Baseline items
```
baseline_items.json             → data/baseline/items.json
baseline_items_v2.json          → data/baseline/items_v2.json
optimized_items.json            → data/optimized/items.json
optimized_items_v2.json         → data/optimized/items_v2.json
```

### Test data и results
```
test_items.json                 → data/test/items.json
test_diagnostic_request.json    → data/test/diagnostic_request.json
lesson_generation_comparison.json → data/test/lesson_comparison.json
lesson_response.json            → data/examples/lesson_response.json
test_optimize_lesson_response.json → data/test/lesson_optimize.json
server_contracts_export.json    → data/contracts/server_contracts.json
server_intel.json               → data/intelligence/server_intel.json
learning_taxonomy_v0_1.json     → data/taxonomy/learning_taxonomy_v0_1.json
```

---

## PowerShell ТЕСТЫ (10+ файлов)

### Основные тесты
```
test_client_v1.ps1              → tests/powershell/client-v1.ps1
test_desktop_client_compat.ps1  → tests/powershell/desktop-client-compat.ps1
test_bug_report_quick.ps1       → tests/powershell/bug-report-quick.ps1
test_production_simple.ps1      → tests/powershell/production-simple.ps1
test_production_baseline.ps1    → tests/powershell/production-baseline.ps1
```

### Feature-specific
```
test_lesson_generation_auth.ps1 → tests/powershell/lesson-generation-auth.ps1
test_learning_plan.ps1          → tests/powershell/learning-plan.ps1
test_optimize_lesson.ps1        → tests/powershell/optimize-lesson.ps1
test_optimize_lesson_simple.ps1 → tests/powershell/optimize-lesson-simple.ps1
test_prompt_testing.ps1         → tests/powershell/prompt-testing.ps1
test_prompt_v2_performance.ps1  → tests/powershell/prompt-v2-performance.ps1
test_prompt_v2_simple.ps1       → tests/powershell/prompt-v2-simple.ps1
test_recommendations_endpoint.ps1 → tests/powershell/recommendations-endpoint.ps1
test_specialized_comprehensive.ps1 → tests/powershell/specialized-comprehensive.ps1
test_v2_minimal.ps1             → tests/powershell/v2-minimal.ps1
```

---

## WINDOWS SCRIPTS (2 файла)

```
analyze_v2_results.ps1          → scripts/windows/analyze_v2_results.ps1
```

---

## ИТОГО

- **Документация:** 45+ файлов → docs/ (с подкатегориями)
- **Тесты Python:** 20+ файлов → tests/ (структурированные)
- **Скрипты:** 30+ файлов → scripts/ (с subfolders)
- **Данные:** 12+ JSON файлов → data/ (с типами)
- **PowerShell:** 10+ файлов → tests/powershell/
- **Примеры:** 2 файла → examples/

### Результат
- **ROOT файлы:** ~50+ (BEFOДОБРО)
- **ROOT файлы:** ~15 (ПОСЛЕ: README, Dockerfile, docker-compose, requirements, .env.example, setup.py, etc.)
- **Экономия пространства:** 70% сокращение беспорядка в root
