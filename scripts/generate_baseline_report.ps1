param(
  [string]$DateStamp = (Get-Date -Format "yyyy-MM-dd")
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path ".").Path
$reportDir = Join-Path $repoRoot "reports/baseline/$DateStamp"
New-Item -ItemType Directory -Force $reportDir | Out-Null

$branch = git branch --show-current
$commit = git rev-parse HEAD
$shortCommit = git rev-parse --short HEAD
$statusCount = (git status --short | Measure-Object).Count

@"
Baseline Date: $DateStamp
Canonical Root: $repoRoot
Branch: $branch
Commit: $commit
Short Commit: $shortCommit
Working tree status lines: $statusCount
"@ | Set-Content (Join-Path $reportDir "baseline_metadata.txt")

git status --short | Set-Content (Join-Path $reportDir "git_status_short.txt")
git diff --name-status | Set-Content (Join-Path $reportDir "git_diff_name_status.txt")
git worktree list | Set-Content (Join-Path $reportDir "git_worktree_list.txt")

python -m pytest --collect-only -q | Tee-Object (Join-Path $reportDir "tests_collect_only.txt")
$collectExit = $LASTEXITCODE

python -m pytest -q | Tee-Object (Join-Path $reportDir "tests_run_q.txt")
$testExit = $LASTEXITCODE

if (Test-Path "scripts/check_route_registration.py") {
  python scripts/check_route_registration.py | Tee-Object (Join-Path $reportDir "route_registration_check.txt")
  $routeCheckExit = $LASTEXITCODE
} else {
  "scripts/check_route_registration.py not found" | Set-Content (Join-Path $reportDir "route_registration_check.txt")
  $routeCheckExit = 0
}

$mainRoutes = if (Get-Command rg -ErrorAction SilentlyContinue) {
  (rg "^\s+@app\.(get|post|put|patch|delete)\(" app/main.py | Measure-Object).Count
} else {
  0
}

$routerRoutes = if ((Get-Command rg -ErrorAction SilentlyContinue) -and (Test-Path "app/api")) {
  (rg "^\s+@router\.(get|post|put|patch|delete)\(" app/api -g "*.py" | Measure-Object).Count
} else {
  0
}

@"
main.py inline route decorators: $mainRoutes
app/api router decorators: $routerRoutes
"@ | Set-Content (Join-Path $reportDir "route_map_counts.txt")

if (Get-Command rg -ErrorAction SilentlyContinue) {
  rg "^\s+@app\.(get|post|put|patch|delete)\(" app/main.py | Set-Content (Join-Path $reportDir "main_inline_routes.txt")
  if (Test-Path "app/api") {
    rg "^\s+@router\.(get|post|put|patch|delete)\(" app/api -g "*.py" | Set-Content (Join-Path $reportDir "router_decorators.txt")
  }
}

@'
import csv
from pathlib import Path

from app.main import create_app

app = create_app()
rows = []
for route in app.routes:
    methods = getattr(route, "methods", None)
    path = getattr(route, "path", None)
    endpoint = getattr(route, "endpoint", None)
    if not methods or not path:
        continue
    for method in sorted(m for m in methods if m not in {"HEAD", "OPTIONS"}):
        endpoint_name = getattr(endpoint, "__name__", "")
        endpoint_mod = getattr(endpoint, "__module__", "")
        rows.append((method, path, endpoint_mod, endpoint_name))

rows = sorted(set(rows), key=lambda r: (r[0], r[1], r[2], r[3]))
report_dir = Path("reports") / "baseline" / "__DATE_STAMP__"
report_dir.mkdir(parents=True, exist_ok=True)

with (report_dir / "route_map.csv").open("w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["method", "path", "endpoint_module", "endpoint_name"])
    writer.writerows(rows)

with (report_dir / "route_map.txt").open("w", encoding="utf-8") as f:
    for method, path, endpoint_mod, endpoint_name in rows:
        f.write(f"{method:6} {path:60} {endpoint_mod}.{endpoint_name}\n")

print(f"ROUTES:{len(rows)}")
'@.Replace("__DATE_STAMP__", $DateStamp) | python - | Tee-Object (Join-Path $reportDir "route_map_generation.log")
$routeMapExit = $LASTEXITCODE

@'
import ast
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

root = Path(".").resolve()
app = root / "app"
py_files = [p for p in app.rglob("*.py") if "__pycache__" not in p.parts]

edge_counter = Counter()
imports_by_file = defaultdict(set)
imported_by = Counter()

for path in py_files:
    rel = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name.startswith("app"):
                    imports_by_file[rel].add(name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level and not module:
                continue
            if module.startswith("app"):
                imports_by_file[rel].add(module)

for src, targets in imports_by_file.items():
    for dst in sorted(targets):
        edge_counter[(src, dst)] += 1
        imported_by[dst] += 1

basename_groups = defaultdict(list)
for path in py_files:
    basename_groups[path.name].append(path.relative_to(root).as_posix())
basename_dupes = {k: sorted(v) for k, v in basename_groups.items() if len(v) > 1}

hash_groups = defaultdict(list)
for path in py_files:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    hash_groups[digest].append(path.relative_to(root).as_posix())
content_dupes = {k: sorted(v) for k, v in hash_groups.items() if len(v) > 1}

summary = {
    "app_python_files": len(py_files),
    "import_graph": {
        "internal_importing_files": len(imports_by_file),
        "internal_edges": len(edge_counter),
        "top_imported_modules": imported_by.most_common(30),
        "top_importing_files": Counter({k: len(v) for k, v in imports_by_file.items()}).most_common(30),
    },
    "duplicates": {
        "duplicate_basenames_count": len(basename_dupes),
        "duplicate_content_groups_count": len(content_dupes),
    },
}

report_dir = root / "reports" / "baseline" / "__DATE_STAMP__"
report_dir.mkdir(parents=True, exist_ok=True)

(report_dir / "import_graph_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
(report_dir / "duplicate_basenames.json").write_text(json.dumps(basename_dupes, indent=2), encoding="utf-8")
(report_dir / "duplicate_content_hash_groups.json").write_text(json.dumps(content_dupes, indent=2), encoding="utf-8")

with (report_dir / "import_edges_top50.txt").open("w", encoding="utf-8") as f:
    for (src, dst), _ in edge_counter.most_common(50):
        f.write(f"{src} -> {dst}\n")

with (report_dir / "duplicate_basenames_top30.txt").open("w", encoding="utf-8") as f:
    for name, paths in sorted(basename_dupes.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:30]:
        f.write(f"[{name}] count={len(paths)}\n")
        for p in paths:
            f.write(f"  - {p}\n")

with (report_dir / "duplicate_content_top30.txt").open("w", encoding="utf-8") as f:
    for digest, paths in sorted(content_dupes.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:30]:
        f.write(f"[sha256:{digest[:12]}] count={len(paths)}\n")
        for p in paths:
            f.write(f"  - {p}\n")

print(json.dumps(summary, indent=2))
'@.Replace("__DATE_STAMP__", $DateStamp) | python - | Tee-Object (Join-Path $reportDir "import_graph_generation.log")
$importGraphExit = $LASTEXITCODE

@"
pytest_collect_exit_code: $collectExit
pytest_run_exit_code: $testExit
route_check_exit_code: $routeCheckExit
route_map_exit_code: $routeMapExit
import_graph_exit_code: $importGraphExit
"@ | Set-Content (Join-Path $reportDir "command_exit_codes.txt")

Write-Output "Baseline artifacts created in: $reportDir"
Write-Output "pytest run exit code: $testExit"
exit 0
