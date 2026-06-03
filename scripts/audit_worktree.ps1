[CmdletBinding()]
param(
    [string]$OutputPath = "",
    [int]$Top = 40
)

$ErrorActionPreference = "Stop"

$repoRoot = (git rev-parse --show-toplevel).Trim()
Set-Location $repoRoot

$status = @(git status --porcelain=v1)

function Convert-StatusRow {
    param([string]$Row)

    $code = $Row.Substring(0, 2)
    $path = ($Row.Substring(3)).Trim()
    $top = ($path -split '[\\/]')[0]
    [pscustomobject]@{
        Code = $code
        Path = $path
        Top = $top
        Deleted = ($code -match 'D')
        Modified = ($code -match 'M|A|R|C|T')
        Untracked = ($code -eq '??')
    }
}

function Get-CleanupBucket {
    param([pscustomobject]$Item)

    $path = ($Item.Path -replace '\\', '/')
    $top = ($Item.Top -replace '\\', '/')

    $generatedDirs = @(
        "node_modules",
        ".seed_artifacts",
        ".tmp_openclaw_extract",
        "test_artifacts",
        "test_path",
        "optimizer_logs",
        "optimizer_logs_temp",
        "mode_test_logs",
        "response_capture_logs",
        "extended_test_logs",
        "dynamic_test_logs",
        "final_test_logs",
        "prompt_test_results"
    )

    $generatedFilePatterns = @(
        '^scripts/_.*\.py$',
        '^scripts/bench_.*\.txt$',
        '^scripts/.*_results\.txt$',
        '^scripts/startup_trace\.txt$',
        '^scripts/detour_dist\.txt$'
    )

    $neoEatsProductPatterns = @(
        '^app/api/(cooking|inventory_orders_vision_routes|neoeats_chat|neoeats_profile_routes|receipts)\.py$',
        '^app/services/(neoeats_.*|receipt_vision_engine|product_normalize|pantry_normalizer|inventory_provider)\.py$',
        '^app/infrastructure/db/(neoeats_db|pgvector_store|seed_catalog)\.py$',
        '^app/infrastructure/embeddings/',
        '^app/core/(neoeats_blocks|embeddings)\.py$',
        '^app/catalog/'
    )

    foreach ($pattern in $neoEatsProductPatterns) {
        if ($path -match $pattern) {
            return "NEOEATS_PUBLIC_BETA"
        }
    }

    $currentWorkPatterns = @(
        '^\.gitignore$',
        '^\.env\.public\.example$',
        '^\.github/workflows/catalog-validation\.yml$',
        '^\.github/workflows/full-tests\.yml$',
        '^\.github/workflows/integration-tests\.yml$',
        '^\.github/workflows/lint\.yml$',
        '^\.github/workflows/module-registry-validation\.yml$',
        '^\.github/workflows/real-llm-smoke\.yml$',
        '^\.github/workflows/route-registration-sanity\.yml$',
        '^\.github/workflows/security-gates\.yml$',
        '^\.github/workflows/server-intel-drift\.yml$',
        '^\.github/workflows/simulation-tests\.yml$',
        '^\.github/workflows/smoke-tests\.yml$',
        '^Caddyfile$',
        '^cloudflared/config\.example\.yml$',
        '^docker-compose\.public\.yml$',
        '^README\.md$',
        '^SOURCE_OF_TRUTH\.md$',
        '^PROBLEMS_AND_TASKS\.md$',
        '^app/api/actions_saga_routes\.py$',
        '^app/api/admin_routes\.py$',
        '^app/api/auth_routes\.py$',
        '^app/api/diagnostics_routes\.py$',
        '^app/api/inventory_orders_vision_routes\.py$',
        '^app/api/learning_feedback_monitoring_routes\.py$',
        '^app/api/lessons_routes\.py$',
        '^app/api/neoeats_chat\.py$',
        '^app/api/neoeats_profile_routes\.py$',
        '^app/api/receipts\.py$',
        '^app/core/ab_testing\.py$',
        '^app/core/validators/validators/repair\.py$',
        '^app/infrastructure/db/neoeats_db\.py$',
        '^app/services/neoeats_rag_memory\.py$',
        '^app/services/neoeats_recipe_card\.py$',
        '^app/services/diagnostic/engine\.py$',
        '^app/services/learning_plan\.py$',
        '^app/services/pantry_normalizer\.py$',
        '^app/services/pipeline/pipeline/steps\.py$',
        '^app/services/product_normalize\.py$',
        '^app/services/receipt_vision_engine\.py$',
        '^docs/SYSTEM_ANALYSIS_AND_DEVELOPMENT_PLAN_2026-05-19\.md$',
        '^docs/STATE_MARK_2026-05-19\.md$',
        '^docs/PROJECT_CLASSIFICATION_2026-05-19\.md$',
        '^docs/CLEANUP_INVENTORY_2026-05-19\.md$',
        '^docs/PUBLIC_RUNTIME_RUNBOOK_2026-05-19\.md$',
        '^docs/guides/DOCUMENTATION_INDEX\.md$',
        '^docs/VERIFY_IMPORTS_AUDIT_2026-05-20\.md$',
        '^docs/TEST_COVERAGE_CLEANUP_2026-05-20\.md$',
        '^scripts/audit_deleted_references\.ps1$',
        '^scripts/audit_worktree\.ps1$',
        '^scripts/diagnostics/check_production_ready\.py$',
        '^scripts/restore_public_runtime\.ps1$',
        '^scripts/smoke_public_neoeats\.ps1$',
        '^scripts/verify/verify_ci_security\.py$',
        '^tests/unit/test_auth_open_registration\.py$',
        '^tests/unit/test_neoeats_cooking_complete\.py$',
        '^tests/unit/test_neoeats_cooking_plan\.py$',
        '^tests/unit/test_neoeats_profile_routes\.py$',
        '^tests/unit/test_neoeats_rag_memory\.py$',
        '^tests/unit/test_neoeats_vision_geometry\.py$',
        '^tests/unit/test_receipt_confirm_routes\.py$',
        '^tests/unit/test_receipt_fallback_no_fake_items\.py$',
        '^tests/TEST_SUITE\.md$'
    )
    foreach ($pattern in $currentWorkPatterns) {
        if ($path -match $pattern) {
            return "COMMIT_NOW"
        }
    }

    $verifiedReplacedDeletionPatterns = @(
        '^\.github/dependabot\.yml$',
        '^\.github/workflows/(ci|ci-validation|coverage|openapi|photo-tests|security-scan)\.yml$',
        '^app/realtime/',
        '^app/optimizer/',
        '^app/[^/]+\.py$',
        '^app/pipeline/',
        '^app/monitoring/metrics\.py$'
    )
    if ($Item.Deleted) {
        foreach ($pattern in $verifiedReplacedDeletionPatterns) {
            if ($path -match $pattern) {
                return "REPLACED_CLEANUP_READY"
            }
        }

        if ($path -match '^tests/.*\.py$' -or $path -match '^scripts/test_.*\.py$') {
            return "TEST_COVERAGE_REBUILD"
        }
    }

    if ($Item.Untracked) {
        foreach ($pattern in $generatedFilePatterns) {
            if ($path -match $pattern) {
                return "IGNORE_ONLY"
            }
        }

        if (
            $path -match '(^|/)(logs|\.vite|\.pytest_cache|dist|build|node_modules)(/|$)' -or
            $path -match '\.(log|tmp|db|sqlite|sqlite3|zip)$' -or
            $generatedDirs -contains $top -or
            $top -match '^multi_phase_'
        ) {
            return "IGNORE_ONLY"
        }
    }

    if ($Item.Deleted -and (
            $generatedDirs -contains $top -or
            $top -match '^multi_phase_' -or
            $path -match '^reports/baseline/'
        )) {
        return "DELETE_IN_CLEANUP_BRANCH"
    }

    if ($path -match '^app/core/agent/' -or
        $path -match '^app/api/(agent|agent_integration|console|marketplace|tenant_governance|saga_blueprints)' -or
        $path -match '^app/(agent_sandbox_worker|billing_service|career_upskilling)\.py$') {
        return "AGENT_PLATFORM_REVIEW"
    }

    if ($path -match '^app/core/realtime/' -or
        $path -match '^app/infrastructure/realtime/' -or
        $path -match '^app/models/realtime/') {
        return "REALTIME_PLATFORM_REVIEW"
    }

    if ($path -match '^app/infrastructure/' -or
        $path -match '^app/(main|settings|dependencies|dependency_check|key_management|worker_main)\.py$') {
        return "INFRASTRUCTURE_REVIEW"
    }

    if ($path -match '^app/api/' -or
        $path -match '^app/services/' -or
        $path -match '^app/core/' -or
        $path -match '^app/models/' -or
        $path -match '^app/validators/' -or
        $path -match '^app/(auth|ai_adapters|diagnostic_core|diagnostic_session|lesson_engine|lesson_engine_pipeline|optimizer_mode|performance_monitor|prompt_testing|rate_limiter|specialized_tests)\.py$') {
        return "PLATFORM_APP_REVIEW"
    }

    if ($path -match '^app/') {
        return "ACTIVE_CODE_REVIEW"
    }

    if ($path -match '^tests/') {
        return "TEST_REVIEW"
    }

    if ($path -match '^scripts/') {
        return "SCRIPT_REVIEW"
    }

    if ($path -match '^migrations/') {
        return "MIGRATION_REVIEW"
    }

    if ($path -match '^\.github/') {
        return "CI_REVIEW"
    }

    if ($path -match '(^|/)(REPORT|SUMMARY|ROADMAP|TASKS|AUDIT|GUIDE|PLAYBOOK|BLUEPRINT|DEPLOYMENT|IMPLEMENTATION|INTEGRATION|DISCOVERY|WORKLOG|PHASE_|FINAL_)' -or
        $path -match '\.(md|txt|json|yaml|yml|sql)$') {
        return "ARCHIVE_REVIEW"
    }

    return "MANUAL_REVIEW"
}

$rows = @($status | ForEach-Object { Convert-StatusRow $_ })
foreach ($row in $rows) {
    $row | Add-Member -NotePropertyName Bucket -NotePropertyValue (Get-CleanupBucket $row)
}

$summary = [pscustomobject]@{
    GeneratedAt = (Get-Date).ToString("s")
    RepoRoot = $repoRoot
    Total = $rows.Count
    Deleted = @($rows | Where-Object { $_.Deleted }).Count
    Modified = @($rows | Where-Object { $_.Modified -and -not $_.Untracked }).Count
    Untracked = @($rows | Where-Object { $_.Untracked }).Count
}

$byTop = @(
    $rows |
        Group-Object Top |
        Sort-Object Count -Descending |
        Select-Object -First $Top |
        ForEach-Object {
            $groupRows = @($_.Group)
            [pscustomobject]@{
                Top = $_.Name
                Total = $_.Count
                Deleted = @($groupRows | Where-Object { $_.Deleted }).Count
                Modified = @($groupRows | Where-Object { $_.Modified -and -not $_.Untracked }).Count
                Untracked = @($groupRows | Where-Object { $_.Untracked }).Count
            }
        }
)

$byBucket = @(
    $rows |
        Group-Object Bucket |
        Sort-Object Count -Descending |
        ForEach-Object {
            $groupRows = @($_.Group)
            [pscustomobject]@{
                Bucket = $_.Name
                Total = $_.Count
                Deleted = @($groupRows | Where-Object { $_.Deleted }).Count
                Modified = @($groupRows | Where-Object { $_.Modified -and -not $_.Untracked }).Count
                Untracked = @($groupRows | Where-Object { $_.Untracked }).Count
            }
        }
)

$generatedCandidates = @(
    $rows |
        Where-Object {
            $scratchGenerated = $false
            foreach ($pattern in @(
                '^scripts/_.*\.py$',
                '^scripts/bench_.*\.txt$',
                '^scripts/.*_results\.txt$',
                '^scripts/startup_trace\.txt$',
                '^scripts/detour_dist\.txt$'
            )) {
                if ($_.Path -match $pattern) {
                    $scratchGenerated = $true
                    break
                }
            }

            $_.Untracked -and (
                $scratchGenerated -or
                $_.Path -match '(^|/)(logs|\.vite|\.pytest_cache|dist|build|node_modules)(/|$)' -or
                $_.Path -match '\.(log|tmp|db|sqlite|sqlite3|zip)$' -or
                $_.Top -match '^(\.seed_artifacts|\.tmp_openclaw_extract|test_artifacts|optimizer_logs|optimizer_logs_temp|mode_test_logs|response_capture_logs|extended_test_logs|dynamic_test_logs|final_test_logs)$' -or
                $_.Top -match '^multi_phase_'
            )
        } |
        Select-Object -First 200
)

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Worktree Audit")
$lines.Add("")
$lines.Add(("- Generated at: {0}" -f $summary.GeneratedAt))
$lines.Add(("- Repo root: {0}" -f $summary.RepoRoot))
$lines.Add(("- Total status entries: {0}" -f $summary.Total))
$lines.Add(("- Deleted entries: {0}" -f $summary.Deleted))
$lines.Add(("- Modified entries: {0}" -f $summary.Modified))
$lines.Add(("- Untracked entries: {0}" -f $summary.Untracked))
$lines.Add("")
$lines.Add("## Top Directories")
$lines.Add("")
$lines.Add("| Top | Total | Deleted | Modified | Untracked |")
$lines.Add("| --- | ---: | ---: | ---: | ---: |")
foreach ($item in $byTop) {
    $lines.Add(("| {0} | {1} | {2} | {3} | {4} |" -f $item.Top, $item.Total, $item.Deleted, $item.Modified, $item.Untracked))
}
$lines.Add("")
$lines.Add("## Cleanup Buckets")
$lines.Add("")
$lines.Add("| Bucket | Total | Deleted | Modified | Untracked |")
$lines.Add("| --- | ---: | ---: | ---: | ---: |")
foreach ($item in $byBucket) {
    $lines.Add(("| {0} | {1} | {2} | {3} | {4} |" -f $item.Bucket, $item.Total, $item.Deleted, $item.Modified, $item.Untracked))
}
$lines.Add("")
$lines.Add("## Bucket Examples")
$lines.Add("")
foreach ($bucket in @("COMMIT_NOW", "NEOEATS_PUBLIC_BETA", "AGENT_PLATFORM_REVIEW", "REALTIME_PLATFORM_REVIEW", "INFRASTRUCTURE_REVIEW", "PLATFORM_APP_REVIEW", "ACTIVE_CODE_REVIEW", "TEST_REVIEW", "SCRIPT_REVIEW", "MIGRATION_REVIEW", "CI_REVIEW", "REPLACED_CLEANUP_READY", "TEST_COVERAGE_REBUILD", "DELETE_IN_CLEANUP_BRANCH", "ARCHIVE_REVIEW", "IGNORE_ONLY", "MANUAL_REVIEW")) {
    $examples = @($rows | Where-Object { $_.Bucket -eq $bucket } | Select-Object -First 12)
    if ($examples.Count -eq 0) {
        continue
    }
    $lines.Add(("### {0}" -f $bucket))
    $lines.Add("")
    foreach ($item in $examples) {
        $lines.Add(("- {0} {1}" -f $item.Code.Trim(), $item.Path).Trim())
    }
    $lines.Add("")
}
$lines.Add("")
$lines.Add("## Generated Candidates")
$lines.Add("")
if ($generatedCandidates.Count -eq 0) {
    $lines.Add("No obvious untracked generated candidates found.")
} else {
    foreach ($item in $generatedCandidates) {
        $lines.Add(("- {0}" -f $item.Path))
    }
}
$lines.Add("")
$lines.Add("## Recommended Handling")
$lines.Add("")
$lines.Add("- Treat tracked deletions as an explicit cleanup branch/commit, not as shell cleanup.")
$lines.Add("- Remove or ignore untracked generated candidates only after checking they are not fixtures.")
$lines.Add("- Keep feature changes, docs updates, generated cleanup and archive moves in separate commits.")

$text = ($lines -join [Environment]::NewLine)

if ($OutputPath.Trim()) {
    $resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputPath)) {
        $OutputPath
    } else {
        Join-Path $repoRoot $OutputPath
    }
    $parent = Split-Path -Parent $resolvedOutput
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Set-Content -Path $resolvedOutput -Value $text -Encoding UTF8
    Write-Output $resolvedOutput
} else {
    Write-Output $text
}
