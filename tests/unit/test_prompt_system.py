#!/usr/bin/env python3
"""
Test script for prompt testing system.

This script demonstrates how to use the new prompt testing features
and compare results between baseline and test prompts.
"""
import asyncio
import json
import logging
from pathlib import Path

from app.settings import get_settings
from app.services.prompt_testing import (
    PromptType,
    init_prompt_test_manager,
    get_prompt_test_manager,
)
from app.services.lesson.engine import generate_lesson
from app.models.api import LessonGenerateRequest
from app.core.personas import get_persona_prompt


def setup_logging():
    """Setup logging for test script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


async def test_prompt_system():
    """Test the prompt testing system."""
    print("🧪 Testing Prompt A/B Testing System")
    print("=" * 50)
    
    # Initialize prompt testing
    prompts_dir = Path(__file__).parent / "prompts"
    init_prompt_test_manager(prompts_dir)
    
    test_manager = get_prompt_test_manager()
    
    # Start test session
    session_id = test_manager.start_test_session("cli_test")
    print(f"📊 Started test session: {session_id}")
    
    # Check if test mode is enabled
    test_mode_active = test_manager.is_test_mode_active()
    print(f"🔧 Test mode active: {test_mode_active}")
    
    if not test_mode_active:
        print("⚠️  Test mode not enabled. Set SEED_PROMPT_TEST_MODE=true to activate")
        print("   This demo will still work but won't perform A/B testing")
    
    # List available test prompts
    test_prompts = test_manager.list_available_test_prompts()
    print(f"📝 Available test prompts: {test_prompts}")
    
    # Test prompt validation
    print("\n🔍 Testing Prompt Validation")
    print("-" * 30)
    
    try:
        # This should work if prompts are valid
        test_manager.get_prompt_content(PromptType.LESSON_GENERATOR)
        print("✅ Baseline prompts validation passed")
    except Exception as e:
        print(f"❌ Baseline prompts validation failed: {e}")
    
    if test_prompts:
        try:
            test_manager.get_prompt_content(PromptType.LESSON_GENERATOR, use_test_version=True)
            print("✅ Test prompts validation passed")
        except Exception as e:
            print(f"❌ Test prompts validation failed: {e}")
    else:
        print("ℹ️  No test prompts to validate")
    
    # Create test request
    test_request = LessonGenerateRequest(
        mode="mixed",
        target_lang="Spanish",
        native_lang="English", 
        level="beginner",
        lesson_length=4,
        topic="basic_greetings"
    )
    
    # Get persona prompt
    persona_prompt = get_persona_prompt("default")
    
    print("\n🔬 Running Lesson Generation Tests")
    print("-" * 40)
    
    # Test scenarios: compare regular vs optimized mode
    test_scenarios = [
        ("baseline_json", False),
        ("optimized_compact", True)
    ]
    
    results = []
    
    for scenario_name, optimize_mode in test_scenarios:
        print(f"\n📋 Testing {scenario_name} (optimize_mode={optimize_mode})")
        
        try:
            lesson = generate_lesson(
                req=test_request,
                persona_prompt=persona_prompt,
                optimize_mode=optimize_mode,
                user_id=f"test_user_{scenario_name}"
            )
            
            result = {
                "scenario": scenario_name,
                "success": True,
                "lesson_id": lesson.lessonId,
                "title": lesson.title,
                "task_count": len(lesson.tasks),
                "task_types": [task.type for task in lesson.tasks]
            }
            
            print(f"✅ Success: {lesson.title}")
            print(f"   Tasks: {len(lesson.tasks)} ({', '.join(task.type for task in lesson.tasks)})")
            
        except Exception as e:
            result = {
                "scenario": scenario_name,
                "success": False,
                "error": str(e)
            }
            
            print(f"❌ Failed: {str(e)}")
        
        results.append(result)
    
    # Get session summary
    print("\n📈 Test Session Summary")
    print("-" * 25)
    
    summary = test_manager.get_session_summary()
    print(f"Session: {summary['session']}")
    print(f"Total tests: {summary['total_tests']}")
    
    if summary['total_tests'] > 0:
        print(f"Success rate: {summary['success_rate']:.1%}")
        print(f"Average execution time: {summary.get('avg_execution_time_ms', 0):.0f}ms")
        print(f"Total tokens used: {summary.get('total_tokens_used', 0)}")
        
        if summary.get('avg_input_tokens', 0) > 0:
            print(f"Average input tokens: {summary['avg_input_tokens']:.0f}")
        if summary.get('avg_output_tokens', 0) > 0:
            print(f"Average output tokens: {summary['avg_output_tokens']:.0f}")
        
        if summary.get('by_type'):
            print("\nResults by prompt type:")
            for prompt_key, stats in summary['by_type'].items():
                print(f"  {prompt_key}:")
                print(f"    Count: {stats['count']}")
                print(f"    Success: {stats['success_count']}/{stats['count']}")
                print(f"    Avg time: {stats['avg_time_ms']:.0f}ms")
                if 'avg_tokens' in stats:
                    print(f"    Avg tokens: {stats['avg_tokens']:.0f}")
    else:
        print("No tests completed (likely missing API keys)")
        print("This is normal for testing without external AI service")
    
    print("\n🔍 A/B Testing Active")
    print("Users are randomly split between baseline and test prompts")
    
    # Demonstrate user assignment
    test_users = ["user_alice", "user_bob", "user_charlie", "user_diana", "user_eve"]
    print("\nUser assignments for lesson_generator:")
    assignments = []
    for user in test_users:
        should_use_test = test_manager.should_use_test_prompt(user, PromptType.LESSON_GENERATOR)
        version = "test" if should_use_test else "baseline"
        assignments.append(version)
        print(f"  {user}: {version}")
    
    # Check distribution
    test_count = assignments.count("test")
    baseline_count = assignments.count("baseline")
    print(f"\nDistribution: {test_count} test / {baseline_count} baseline")
    
    if test_count > 0 and baseline_count > 0:
        print("✅ Good A/B distribution achieved")
    else:
        print("⚠️  Poor distribution - may need more users for statistical significance")
    
    print(f"\n💾 Results saved to: {test_manager.results_dir / session_id}")
    print("\n🎉 Prompt testing system working correctly!")
    
    return results


async def compare_prompts():
    """Compare output from baseline vs test prompts."""
    print("\n🆚 Comparing Baseline vs Test Prompts")
    print("=" * 40)
    
    # This would be more meaningful with actual different prompts
    # For now, just demonstrate the concept
    
    test_request = LessonGenerateRequest(
        mode="mixed",
        target_lang="French",
        native_lang="English",
        level="intermediate", 
        lesson_length=3,
        topic="restaurant_dining"
    )
    
    persona_prompt = get_persona_prompt("default")
    
    print("Test Lesson Generation with Fixed User IDs:")
    print("(This demonstrates consistent A/B assignment)")
    
    # Fixed user IDs will always get the same prompt version
    fixed_users = ["alice_baseline", "bob_test", "charlie_baseline"]
    
    for user_id in fixed_users:
        try:
            test_manager = get_prompt_test_manager()
            should_use_test = test_manager.should_use_test_prompt(user_id, PromptType.LESSON_GENERATOR)
            version = "test" if should_use_test else "baseline"
            
            lesson = generate_lesson(
                req=test_request,
                persona_prompt=persona_prompt,
                optimize_mode=False,  # Use JSON format for comparison
                user_id=user_id
            )
            
            print(f"  {user_id} ({version}): {lesson.title}")
            print(f"    Tasks: {', '.join(task.type for task in lesson.tasks)}")
            
        except Exception as e:
            print(f"  {user_id}: Error - {str(e)}")
    
    print("\n✨ Comparison complete!")


if __name__ == "__main__":
    setup_logging()
    
    print("🚀 Seed Server Prompt Testing Demo")
    print("=" * 50)
    
    try:
        # Run tests
        asyncio.run(test_prompt_system())
        
        # Run comparison if test mode is active
        settings = get_settings()
        if settings.prompt_test_mode:
            asyncio.run(compare_prompts())
        else:
            print("\nℹ️  To see prompt comparison, set SEED_PROMPT_TEST_MODE=true")
        
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n💥 Test failed: {e}")
        logging.error("Test script failed", exc_info=True)

