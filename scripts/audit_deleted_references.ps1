[CmdletBinding()]
param(
    [string]$OutputPath = "",
    [int]$MaxHitsPerFile = 8
)

$ErrorActionPreference = "Stop"

$repoRoot = (git rev-parse --show-toplevel).Trim()
Set-Location $repoRoot

$searchGlobs = @(
    "--glob", "!node_modules/**",
    "--glob", "!test_artifacts/**",
    "--glob", "!test_path/**",
    "--glob", "!optimizer_logs/**",
    "--glob", "!optimizer_logs_temp/**",
    "--glob", "!mode_test_logs/**",
    "--glob", "!response_capture_logs/**",
    "--glob", "!extended_test_logs/**",
    "--glob", "!dynamic_test_logs/**",
    "--glob", "!final_test_logs/**",
    "--glob", "!multi_phase_*/**",
    "--glob", "!logs/**",
    "--glob", "!reports/baseline/**",
    "--glob", "!.seed_artifacts/**",
    "--glob", "!.tmp_openclaw_extract/**",
    "--glob", "!scripts/_*.py",
    "--glob", "!scripts/bench_*.txt",
    "--glob", "!scripts/*_results.txt",
    "--glob", "!scripts/startup_trace.txt",
    "--glob", "!scripts/detour_dist.txt"
)

$candidateSearchTargets = @(
    "app",
    "tests",
    "scripts",
    "migrations",
    ".github",
    "pyproject.toml",
    "pytest.ini",
    "alembic.ini",
    ".pre-commit-config.yaml",
    ".dockerignore",
    ".gitignore",
    ".env.example",
    "docker-compose.yml",
    "docker-compose.public.yml",
    "Caddyfile"
)
$searchTargets = @($candidateSearchTargets | Where-Object { Test-Path -LiteralPath $_ })

function Convert-StatusRow {
    param([string]$Row)

    [pscustomobject]@{
        Code = $Row.Substring(0, 2)
        Path = ($Row.Substring(3)).Trim() -replace '\\', '/'
    }
}

function Get-SearchTerms {
    param([string]$Path)

    $terms = New-Object System.Collections.Generic.List[string]
    $withoutExt = $Path -replace '\.[^./]+$', ''
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($Path)
    $module = $withoutExt -replace '/', '.'

    if ($Path.EndsWith(".py")) {
        $replacementDir = Join-Path $repoRoot ($withoutExt -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        if (Test-Path -LiteralPath $replacementDir -PathType Container) {
            return @()
        }
        $terms.Add(("from {0}" -f $module))
        $terms.Add(("import {0}" -f $module))
        if ($module.StartsWith("app.")) {
            $terms.Add(("from app import {0}" -f $stem))
        }
    } elseif ($Path.EndsWith(".ts") -or $Path.EndsWith(".tsx")) {
        $terms.Add($withoutExt)
    } elseif ($Path.EndsWith(".yml") -or $Path.EndsWith(".yaml")) {
        $terms.Add($Path)
    } else {
        $terms.Add($Path)
    }

    return @($terms | Where-Object { $_ -and $_.Trim() } | Select-Object -Unique)
}

function Find-References {
    param(
        [string]$DeletedPath,
        [string[]]$Terms
    )

    $hits = New-Object System.Collections.Generic.List[string]
    foreach ($term in $Terms) {
        if ($hits.Count -ge $MaxHitsPerFile) {
            break
        }

        $rgOutput = @(& rg --fixed-strings --line-number @searchGlobs -- "$term" @searchTargets 2>$null)
        $global:LASTEXITCODE = 0
        foreach ($line in $rgOutput) {
            if ($hits.Count -ge $MaxHitsPerFile) {
                break
            }
            $normalizedLine = $line -replace '\\', '/'
            if ($normalizedLine -like ("./{0}:*" -f $DeletedPath)) {
                continue
            }
            if ($normalizedLine -match '^./scripts/audit_deleted_references\.ps1:') {
                continue
            }
            $hits.Add(("{0} :: {1}" -f $term, $normalizedLine))
        }
    }
    return @($hits | Select-Object -Unique)
}

function Test-RelativeImportTargetExists {
    param(
        [string]$HitPath,
        [string]$Dots,
        [string]$Stem
    )

    $relativeHitPath = $HitPath -replace '/', [System.IO.Path]::DirectorySeparatorChar
    $absoluteHitPath = Join-Path $repoRoot $relativeHitPath
    $baseDir = Split-Path -Parent $absoluteHitPath
    $levelsUp = [Math]::Max(0, $Dots.Length - 1)

    for ($i = 0; $i -lt $levelsUp; $i++) {
        $baseDir = Split-Path -Parent $baseDir
        if (-not $baseDir) {
            return $false
        }
    }

    $moduleFile = Join-Path $baseDir ("{0}.py" -f $Stem)
    $moduleDir = Join-Path $baseDir $Stem

    return (
        (Test-Path -LiteralPath $moduleFile -PathType Leaf) -or
        (Test-Path -LiteralPath $moduleDir -PathType Container)
    )
}

function Find-BrokenRelativeReferences {
    param(
        [string]$DeletedPath,
        [string]$Stem
    )

    if (-not ($DeletedPath.StartsWith("app/") -and $DeletedPath.EndsWith(".py"))) {
        return @()
    }

    $hits = New-Object System.Collections.Generic.List[string]
    $escapedStem = [Regex]::Escape($Stem)
    $rgOutput = @(& rg --line-number @searchGlobs -- "$Stem" @searchTargets 2>$null)
    $global:LASTEXITCODE = 0

    foreach ($line in $rgOutput) {
        if ($hits.Count -ge $MaxHitsPerFile) {
            break
        }

        $normalizedLine = $line -replace '\\', '/'
        if ($normalizedLine -like ("./{0}:*" -f $DeletedPath) -or $normalizedLine -like ("{0}:*" -f $DeletedPath)) {
            continue
        }
        if ($normalizedLine -match '^(./)?scripts/audit_deleted_references\.ps1:') {
            continue
        }

        $parts = $normalizedLine -split ':', 3
        if ($parts.Count -lt 3) {
            continue
        }

        $hitPath = $parts[0]
        $content = $parts[2]
        $dots = $null

        if ($content -match ("from\s+(\.+)\s+import\s+.*\b{0}\b" -f $escapedStem)) {
            $dots = $Matches[1]
        } elseif ($content -match ("from\s+(\.+){0}(\b|\.|\s+import)" -f $escapedStem)) {
            $dots = $Matches[1]
        }

        if (-not $dots) {
            continue
        }

        if (Test-RelativeImportTargetExists -HitPath $hitPath -Dots $dots -Stem $Stem) {
            continue
        }

        $hits.Add(("relative import missing target :: {0}" -f $normalizedLine))
    }

    return @($hits | Select-Object -Unique)
}

$statusRows = @(git status --porcelain=v1 | ForEach-Object { Convert-StatusRow $_ })
$deleted = @(
    $statusRows |
        Where-Object {
            $_.Code -match 'D' -and
            $_.Path -match '^(\.github|app|tests|scripts|migrations)/'
        } |
        Sort-Object Path
)

$results = @(
    foreach ($item in $deleted) {
        $terms = @(Get-SearchTerms -Path $item.Path)
        $stem = [System.IO.Path]::GetFileNameWithoutExtension($item.Path)
        $hits = @(
            @(Find-References -DeletedPath $item.Path -Terms $terms)
            @(Find-BrokenRelativeReferences -DeletedPath $item.Path -Stem $stem)
        )
        [pscustomobject]@{
            Path = $item.Path
            Terms = ($terms -join ", ")
            Status = if ($hits.Count -gt 0) { "REFERENCED" } else { "NO_REFERENCES_FOUND" }
            HitCount = $hits.Count
            Hits = $hits
        }
    }
)

$summary = $results | Group-Object Status | Sort-Object Name

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Deleted Reference Audit")
$lines.Add("")
$lines.Add(("- Generated at: {0}" -f (Get-Date).ToString("s")))
$lines.Add(("- Repo root: {0}" -f $repoRoot))
$lines.Add(("- Deleted files checked: {0}" -f $results.Count))
$lines.Add("")
$lines.Add("## Summary")
$lines.Add("")
$lines.Add("| Status | Count |")
$lines.Add("| --- | ---: |")
foreach ($group in $summary) {
    $lines.Add(("| {0} | {1} |" -f $group.Name, $group.Count))
}
$lines.Add("")
$lines.Add("## Referenced Deleted Files")
$lines.Add("")
$referenced = @($results | Where-Object { $_.Status -eq "REFERENCED" })
if ($referenced.Count -eq 0) {
    $lines.Add("No referenced deleted files were found by literal or missing-target relative import search.")
} else {
    foreach ($item in $referenced) {
        $lines.Add(("### {0}" -f $item.Path))
        $lines.Add("")
        $lines.Add(("- Search terms: {0}" -f $item.Terms))
        foreach ($hit in $item.Hits) {
            $lines.Add(("- {0}" -f $hit))
        }
        $lines.Add("")
    }
}
$lines.Add("")
$lines.Add("## No Reference Candidates")
$lines.Add("")
foreach ($item in @($results | Where-Object { $_.Status -eq "NO_REFERENCES_FOUND" } | Select-Object -First 120)) {
    $lines.Add(("- {0}" -f $item.Path))
}

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

exit 0
