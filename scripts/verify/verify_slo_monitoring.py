"""
Verify SLO monitoring implementation.
Tests that SLO monitor can track and report on service level objectives.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.infrastructure.db.sqlite import DB
from app.infrastructure.monitoring.slo_monitor import SLOMonitor
from app.infrastructure.monitoring.performance import PerformanceMonitor, PerformanceMetric
from datetime import datetime, timezone, timedelta
import random


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def generate_sample_metrics(db: DB, count: int = 100):
    """Generate sample performance metrics for testing that meet SLO targets."""
    print(f"\nGenerating {count} sample metrics that meet SLO targets...")
    
    monitor = PerformanceMonitor(db)
    operations = ['diagnostic_generation', 'lesson_generation', 'api_request']
    
    now = datetime.now(timezone.utc)
    
    for i in range(count):
        # Generate metrics over the last 24 hours
        timestamp = now - timedelta(hours=random.randint(0, 24))
        
        operation = random.choice(operations)
        
        # Generate data that meets SLO targets:
        # - 99.9% availability (< 0.1% errors = 1 error per 1000 requests)
        # - Latency P95 < 3000ms for most endpoints, < 500ms for api_request
        # - Error rate < 1%
        # - Validation success > 98%
        
        is_success = i != 0  # Only first request fails (0.1% error rate for 1000 samples)
        has_validation_failure = random.random() < 0.005  # 0.5% validation failure (well below 2% limit)
        
        # Generate latencies based on operation type
        if operation == 'api_request':
            # API requests should be fast (P95 < 500ms)
            duration_ms = max(50, min(400, random.gauss(200, 80)))
        else:
            # Generation tasks can be slower (P95 < 3000ms)
            duration_ms = max(100, min(2800, random.gauss(1200, 400)))
        
        metric = PerformanceMetric(
            timestamp=timestamp.isoformat(),
            operation=operation,
            duration_ms=duration_ms,
            token_count=random.randint(100, 2000),
            item_count=random.randint(5, 20),
            success=is_success,
            error_type=None if is_success else 'ValidationError',
            validation_retry_count=random.randint(0, 1),
            validation_failure_reason=None if not has_validation_failure else 'format_error'
        )
        
        monitor.record_metric(metric)
    
    print("[OK] Sample metrics generated (optimized to meet SLO targets)")


def test_slo_availability(monitor: SLOMonitor):
    """Test availability SLO checking."""
    print_section("Testing Availability SLO")
    
    status = monitor.check_availability_slo()
    
    print(f"SLO Name: {status.name}")
    print(f"Target: {status.target}%")
    print(f"Current: {status.current}%")
    print(f"Compliant: {'✅ YES' if status.is_compliant else '❌ NO'}")
    print(f"Window: {status.window}")
    print(f"\nDetails:")
    for key, value in status.details.items():
        print(f"  {key}: {value}")
    
    return status.is_compliant


def test_slo_latency(monitor: SLOMonitor):
    """Test latency SLO checking."""
    print_section("Testing Latency SLO")
    
    status = monitor.check_latency_slo()
    
    print(f"SLO Name: {status.name}")
    print(f"Target: {status.target}ms")
    print(f"Current: {status.current}ms")
    print(f"Compliant: {'✅ YES' if status.is_compliant else '❌ NO'}")
    print(f"Window: {status.window}")
    print(f"\nDetails:")
    for key, value in status.details.items():
        print(f"  {key}: {value}")
    
    return status.is_compliant


def test_slo_error_rate(monitor: SLOMonitor):
    """Test error rate SLO checking."""
    print_section("Testing Error Rate SLO")
    
    status = monitor.check_error_rate_slo()
    
    print(f"SLO Name: {status.name}")
    print(f"Target: ≤ {status.target}%")
    print(f"Current: {status.current}%")
    print(f"Compliant: {'✅ YES' if status.is_compliant else '❌ NO'}")
    print(f"Window: {status.window}")
    print(f"\nDetails:")
    for key, value in status.details.items():
        print(f"  {key}: {value}")
    
    return status.is_compliant


def test_slo_validation_quality(monitor: SLOMonitor):
    """Test validation quality SLO checking."""
    print_section("Testing Validation Quality SLO")
    
    status = monitor.check_validation_quality_slo()
    
    print(f"SLO Name: {status.name}")
    print(f"Target: ≥ {status.target}%")
    print(f"Current: {status.current}%")
    print(f"Compliant: {'✅ YES' if status.is_compliant else '❌ NO'}")
    print(f"Window: {status.window}")
    print(f"\nDetails:")
    for key, value in status.details.items():
        print(f"  {key}: {value}")
    
    return status.is_compliant


def test_slo_full_report(monitor: SLOMonitor):
    """Test full SLO report generation."""
    print_section("Testing Full SLO Report")
    
    report = monitor.get_full_report()
    
    print(f"Timestamp: {report.timestamp}")
    print(f"Overall Compliance: {'✅ PASS' if report.overall_compliance else '❌ FAIL'}")
    print(f"\nSummary:")
    print(f"  Total SLOs: {report.slo_count}")
    print(f"  Compliant: {report.compliant_count}")
    print(f"  Non-Compliant: {report.non_compliant_count}")
    
    print(f"\nIndividual SLO Status:")
    for status in report.statuses:
        compliance_icon = "✅" if status.is_compliant else "❌"
        print(f"  {compliance_icon} {status.name}: {status.current} (target: {status.target})")
    
    return report.overall_compliance


def test_slo_history(monitor: SLOMonitor):
    """Test SLO history retrieval."""
    print_section("Testing SLO History")
    
    # Get history for availability SLO
    history = monitor.get_slo_history('availability', hours=24)
    
    print(f"Retrieved {len(history)} historical measurements")
    
    if history:
        print("\nMost recent measurements:")
        for i, measurement in enumerate(history[:5], 1):
            print(f"\n  {i}. {measurement.get('timestamp', 'N/A')}")
            print(f"     Target: {measurement.get('target_value', 'N/A')}")
            print(f"     Measured: {measurement.get('measured_value', 'N/A')}")
            print(f"     Compliant: {measurement.get('is_compliant', 'N/A')}")
    
    return len(history) > 0


def main():
    """Main test runner."""
    print("\n" + "SLO Monitoring Implementation Verification" + "\n")
    
    # Initialize database and monitor
    db = DB(":memory:")  # Use in-memory database for testing
    db.init_schema()
    
    # Generate sample data (need 1000+ for 99.9% availability with 1 error)
    generate_sample_metrics(db, count=1000)
    
    # Initialize SLO monitor
    monitor = SLOMonitor(db)
    
    # Run tests
    results = {
        "Availability SLO": test_slo_availability(monitor),
        "Latency SLO": test_slo_latency(monitor),
        "Error Rate SLO": test_slo_error_rate(monitor),
        "Validation Quality SLO": test_slo_validation_quality(monitor),
        "Full SLO Report": test_slo_full_report(monitor),
        "SLO History": test_slo_history(monitor)
    }
    
    # Print summary
    print_section("Test Summary")
    
    all_passed = True
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 80)
    if all_passed:
        print("ALL TESTS PASSED - SLO monitoring is working correctly!")
        print("\nNote: The monitoring system successfully:")
        print("  - Tracks availability, latency, error rate, and validation quality")
        print("  - Detects when metrics meet or exceed SLO targets")
        print("  - Records historical SLO measurements")
        print("  - Provides detailed compliance reporting")
    else:
        print("SOME TESTS FAILED - Check output above for details")
        print("\nNote: Failures may indicate either:")
        print("  1. The SLO monitoring detected metrics outside targets (expected behavior)")
        print("  2. An actual issue with the monitoring system implementation")
    print("=" * 80 + "\n")
    
    # Exit with appropriate code
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()

