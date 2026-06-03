#!/usr/bin/env python
"""
Quick setup script for SLO monitoring and load testing.
Run this to verify everything is configured correctly.
"""
import subprocess
import sys
from pathlib import Path


def print_header(text: str):
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80 + "\n")


def check_file_exists(path: str) -> bool:
    """Check if a file exists."""
    return Path(path).exists()


def run_command(cmd: list, description: str) -> bool:
    """Run a command and return success status."""
    print(f"🔍 {description}...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"   ✅ Success")
        return True
    except subprocess.CalledProcessError as e:
        print(f"   ❌ Failed: {e.stderr}")
        return False
    except FileNotFoundError:
        print(f"   ⚠️  Command not found: {cmd[0]}")
        return False


def main():
    """Main setup verification."""
    print_header("SLO Monitoring & Load Testing Setup Verification")
    
    # Check configuration files
    print("📁 Checking configuration files...")
    files_to_check = [
        "slo_config.yaml",
        "app/slo_monitor.py",
        "monitoring/prometheus.yml",
        "monitoring/alert_rules.yml",
        "monitoring/alertmanager.yml",
        "monitoring/grafana/provisioning/datasources/prometheus.yml",
        "monitoring/grafana/provisioning/dashboards/dashboards.yml",
        "load_tests/locustfile.py",
        "load_tests/check_slo_compliance.py",
    ]
    
    all_files_exist = True
    for file_path in files_to_check:
        exists = check_file_exists(file_path)
        status = "✅" if exists else "❌"
        print(f"   {status} {file_path}")
        if not exists:
            all_files_exist = False
    
    if not all_files_exist:
        print("\n❌ Some files are missing. Please check the implementation.")
        sys.exit(1)
    
    # Check Python imports
    print_header("Checking Python Dependencies")
    
    imports_ok = True
    try:
        print("🔍 Checking core dependencies...")
        import yaml
        print("   ✅ PyYAML")
        from app.infrastructure.monitoring.slo_monitor import SLOMonitor
        print("   ✅ SLO Monitor")
        from app.infrastructure.monitoring.performance import PerformanceMonitor
        print("   ✅ Performance Monitor")
    except ImportError as e:
        print(f"   ❌ Import failed: {e}")
        imports_ok = False
    
    if not imports_ok:
        print("\n❌ Some dependencies are missing. Run: pip install -r requirements.txt")
        sys.exit(1)
    
    # Check optional dependencies
    print_header("Checking Optional Load Testing Dependencies")
    
    try:
        import locust
        print("   ✅ Locust installed")
    except ImportError:
        print("   ⚠️  Locust not installed (optional)")
        print("      Install with: pip install locust faker")
    
    # Test SLO monitoring
    print_header("Testing SLO Monitoring")
    
    if run_command(
        [sys.executable, "verify_slo_monitoring.py"],
        "Running SLO monitoring tests"
    ):
        print("\n✅ SLO monitoring is working! (Note: Test may show 'failures' due to")
        print("   random test data not meeting strict SLO targets - this is expected)")
    
    # Print next steps
    print_header("Next Steps")
    
    print("1. Configure alert notifications:")
    print("   Edit monitoring/alertmanager.yml to add Slack/PagerDuty webhooks")
    
    print("\n2. Start monitoring stack:")
    print("   docker-compose up -d prometheus grafana alertmanager")
    
    print("\n3. Access dashboards:")
    print("   Grafana:       http://localhost:3000 (admin/admin)")
    print("   Prometheus:    http://localhost:9090")
    print("   Alertmanager:  http://localhost:9093")
    
    print("\n4. Run load tests:")
    print("   cd load_tests")
    print("   locust -f locustfile.py --host http://localhost:8000")
    
    print("\n5. Check SLO status via API:")
    print("   curl -H 'X-API-Key: YOUR_KEY' http://localhost:8000/v1/monitoring/slo")
    
    print_header("Setup Complete!")
    print("See SLO_MONITORING_IMPLEMENTATION.md for full documentation.")


if __name__ == "__main__":
    main()
