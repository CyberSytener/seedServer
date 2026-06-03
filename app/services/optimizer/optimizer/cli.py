"""
CLI Interface for Optimizer System

Provides command-line interface for running optimizations.

Usage:
    # Run V1 optimizer (prompt only)
    python -m app.services.optimizer.optimizer.cli --version v1 --target prompt_content_creator --iterations 5
    
    # Run V2 optimizer (prompt + validation)
    python -m app.services.optimizer.optimizer.cli --version v2 --target prompt_content_creator --optimize-validation
    
    # Compare versions
    python -m app.services.optimizer.optimizer.cli --compare v1,v2 --target prompt_content_creator
    
    # List sessions
    python -m app.services.optimizer.optimizer.cli --list-sessions
"""
import asyncio
import argparse
import logging
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.optimizer.optimizer import (
    OptimizerManager,
    OptimizationTarget,
    OptimizerVersion,
)
from app.services.optimizer.optimizer.testing import TestCaseLoader, ValidationTestBuilder

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Run optimization for language learning content generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Optimize prompt with V1 (5 iterations)
  python -m app.services.optimizer.optimizer.cli --version v1 --target prompt_content_creator --iterations 5
  
  # Optimize validation rules with V2
  python -m app.services.optimizer.optimizer.cli --version v2 --target validation_rules --optimize-validation-only
  
  # Optimize both prompt and validation
  python -m app.services.optimizer.optimizer.cli --version v2 --target prompt_content_creator --optimize-both
  
  # Compare V1 and V2
  python -m app.services.optimizer.optimizer.cli --compare v1,v2 --target prompt_content_creator --iterations 3
  
  # List all sessions
  python -m app.services.optimizer.optimizer.cli --list-sessions
  
  # List sessions for specific version
  python -m app.services.optimizer.optimizer.cli --list-sessions --version v2
        """
    )
    
    # Version selection
    parser.add_argument(
        "--version",
        type=str,
        choices=["v1", "v2"],
        help="Optimizer version to use (v1=prompt only, v2=prompt+validation)"
    )
    
    # Target selection
    parser.add_argument(
        "--target",
        type=str,
        choices=[
            "prompt_content_creator",
            "prompt_lesson_planner",
            "prompt_validator",
            "validation_rules",
            "validation_weights",
        ],
        help="What to optimize"
    )
    
    # Optimization parameters
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Maximum number of optimization iterations (default: 5)"
    )
    
    parser.add_argument(
        "--threshold",
        type=float,
        default=95.0,
        help="Stability threshold score (default: 95.0)"
    )
    
    # V2-specific options
    parser.add_argument(
        "--optimize-validation-only",
        action="store_true",
        help="V2: Optimize only validation rules, not prompt"
    )
    
    parser.add_argument(
        "--optimize-prompt-only",
        action="store_true",
        help="V2: Optimize only prompt, not validation rules"
    )
    
    parser.add_argument(
        "--optimize-both",
        action="store_true",
        help="V2: Optimize both prompt and validation (default for V2)"
    )
    
    # Test cases
    parser.add_argument(
        "--test-cases",
        type=str,
        help="Path to JSON file with test cases"
    )
    
    parser.add_argument(
        "--use-validation-tests",
        action="store_true",
        help="Use specialized validation stress tests"
    )
    
    parser.add_argument(
        "--use-standard-tests",
        action="store_true",
        help="Use standard test suite (default)"
    )
    
    # Comparison mode
    parser.add_argument(
        "--compare",
        type=str,
        help="Compare multiple versions (comma-separated, e.g., 'v1,v2')"
    )
    
    # Session management
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List all optimization sessions"
    )
    
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from saved state (if available)"
    )
    
    return parser.parse_args()


async def run_single_optimization(args):
    """Run single optimization"""
    manager = OptimizerManager()
    
    # Parse version
    version_map = {
        "v1": OptimizerVersion.V1_PROMPT_ONLY,
        "v2": OptimizerVersion.V2_PROMPT_VALIDATION,
    }
    version = version_map[args.version]
    
    # Parse target
    target = OptimizationTarget(args.target)
    
    # Load test cases
    test_cases = None
    if args.test_cases:
        test_cases_path = Path(args.test_cases)
        test_cases = TestCaseLoader.load_from_file(test_cases_path)
        logger.info(f"Loaded {len(test_cases)} test cases from {test_cases_path}")
    elif args.use_validation_tests:
        test_cases = ValidationTestBuilder.create_validation_stress_tests()
        logger.info(f"Using validation stress tests ({len(test_cases)} cases)")
    else:
        test_cases = TestCaseLoader.create_standard_suite()
        logger.info(f"Using standard test suite ({len(test_cases)} cases)")
    
    # Prepare kwargs
    kwargs = {
        "max_iterations": args.iterations,
        "stability_threshold": args.threshold,
        "resume": args.resume,
    }
    
    # V2-specific options
    if version == OptimizerVersion.V2_PROMPT_VALIDATION:
        if args.optimize_validation_only:
            kwargs["optimize_prompt"] = False
            kwargs["optimize_validation"] = True
        elif args.optimize_prompt_only:
            kwargs["optimize_prompt"] = True
            kwargs["optimize_validation"] = False
        else:  # both or default
            kwargs["optimize_prompt"] = True
            kwargs["optimize_validation"] = True
    
    logger.info(f"Starting optimization: {version.value} -> {target.value}")
    logger.info(f"Parameters: {kwargs}")
    
    # Run optimization
    result = await manager.run_optimization(
        version=version,
        target=target,
        test_cases=test_cases,
        **kwargs
    )
    
    # Print summary
    print("\n" + "="*70)
    print("OPTIMIZATION COMPLETE")
    print("="*70)
    print(f"Session ID: {result.session_id}")
    print(f"Version: {result.version.value}")
    print(f"Target: {result.target.value}")
    print(f"Total Iterations: {len(result.iterations)}")
    print(f"Initial Score: {result.iterations[0].avg_score:.1f}/100")
    print(f"Final Score: {result.iterations[-1].avg_score:.1f}/100")
    print(f"Best Score: {result.best_iteration.avg_score:.1f}/100")
    print(f"Improvement: {result.improvement_delta:+.1f} points")
    print("="*70)
    
    return result


async def run_comparison(args):
    """Run comparison between versions"""
    manager = OptimizerManager()
    
    # Parse versions
    version_strs = args.compare.split(",")
    version_map = {
        "v1": OptimizerVersion.V1_PROMPT_ONLY,
        "v2": OptimizerVersion.V2_PROMPT_VALIDATION,
    }
    versions = [version_map[v.strip()] for v in version_strs]
    
    # Parse target
    target = OptimizationTarget(args.target)
    
    # Load test cases
    if args.test_cases:
        test_cases_path = Path(args.test_cases)
        test_cases = TestCaseLoader.load_from_file(test_cases_path)
    else:
        test_cases = TestCaseLoader.create_standard_suite()
    
    logger.info(f"Comparing versions: {[v.value for v in versions]}")
    logger.info(f"Test cases: {len(test_cases)}")
    
    # Run comparison
    results = await manager.compare_versions(
        versions=versions,
        target=target,
        test_cases=test_cases,
        max_iterations=args.iterations,
        stability_threshold=args.threshold,
    )
    
    # Print comparison
    print("\n" + "="*70)
    print("VERSION COMPARISON COMPLETE")
    print("="*70)
    
    for version_str, result in results.items():
        print(f"\n{version_str}:")
        print(f"  Final Score: {result.iterations[-1].avg_score:.1f}/100")
        print(f"  Best Score: {result.best_iteration.avg_score:.1f}/100")
        print(f"  Improvement: {result.improvement_delta:+.1f} points")
        print(f"  Iterations: {len(result.iterations)}")
    
    print("="*70)


def list_sessions(args):
    """List all sessions"""
    manager = OptimizerManager()
    
    # Parse version filter
    version_filter = None
    if args.version:
        version_map = {
            "v1": OptimizerVersion.V1_PROMPT_ONLY,
            "v2": OptimizerVersion.V2_PROMPT_VALIDATION,
        }
        version_filter = version_map[args.version]
    
    sessions = manager.list_sessions(version=version_filter)
    
    print("\n" + "="*70)
    print("OPTIMIZATION SESSIONS")
    print("="*70)
    
    if not sessions:
        print("No sessions found.")
    else:
        for i, session_dir in enumerate(sessions, 1):
            summary = manager.get_session_summary(session_dir)
            
            if "error" in summary:
                print(f"\n{i}. {session_dir.name}")
                print(f"   Status: Incomplete or corrupted")
            else:
                print(f"\n{i}. {session_dir.name}")
                print(f"   Version: {summary.get('version', 'N/A')}")
                print(f"   Target: {summary.get('target', 'N/A')}")
                print(f"   Best Score: {summary.get('best_iteration', {}).get('avg_score', 'N/A')}/100")
                print(f"   Iterations: {len(summary.get('iterations', []))}")
    
    print("="*70)


def main():
    """Main entry point"""
    args = parse_args()
    
    try:
        if args.list_sessions:
            # List sessions (sync operation)
            list_sessions(args)
        
        elif args.compare:
            # Run comparison
            if not args.target:
                print("Error: --target is required for comparison")
                sys.exit(1)
            
            asyncio.run(run_comparison(args))
        
        elif args.version and args.target:
            # Run single optimization
            asyncio.run(run_single_optimization(args))
        
        else:
            print("Error: Either --version + --target, --compare, or --list-sessions is required")
            print("Use --help for usage information")
            sys.exit(1)
    
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
    
    except Exception as e:
        logger.exception(f"Optimization failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

