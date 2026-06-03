"""
Action Specifications and LLM Guardrails.

This module defines:
1. Standard actions the model can invoke
2. Parameter schemas for each action
3. System prompts to enforce LLM guardrails
4. Validators to ensure model compliance
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ============================================================================
# ACTION SPECIFICATION
# ============================================================================


class ActionSpec(BaseModel):
    """Specification for an action the model can invoke."""
    name: str = Field(description="Unique action name")
    description: str = Field(description="Human-readable description")
    category: str = Field(description="Category: search, booking, create, schedule, notify")
    requires_confirmation: bool = Field(default=False, description="Requires user confirmation")
    external_api: bool = Field(default=False, description="Calls external API")
    max_retries: int = Field(default=3)
    timeout_seconds: int = Field(default=30)
    params_schema: Dict[str, Any] = Field(default_factory=dict, description="JSON schema for params")
    examples: List[Dict[str, Any]] = Field(default_factory=list)
    guardrails: List[str] = Field(default_factory=list, description="Restrictions/guardrails")


# ============================================================================
# PROPERTY/LISTING ACTIONS
# ============================================================================

SEARCH_LISTINGS_SPEC = ActionSpec(
    name="search_listings",
    description="Search property listings by location, price, and amenities",
    category="search",
    requires_confirmation=False,
    external_api=True,
    timeout_seconds=15,
    params_schema={
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City, region, or address"},
            "price_min": {"type": "integer", "description": "Minimum price"},
            "price_max": {"type": "integer", "description": "Maximum price"},
            "beds_min": {"type": "integer", "description": "Minimum bedrooms"},
            "beds_max": {"type": "integer", "description": "Maximum bedrooms"},
            "keywords": {"type": "array", "items": {"type": "string"}, "description": "Amenity keywords (e.g., 'balcony', 'pet-friendly')"},
            "radius_km": {"type": "number", "description": "Search radius in km"},
            "sort_by": {"type": "string", "enum": ["relevance", "price_asc", "price_desc"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        },
        "required": ["location"],
    },
    examples=[
        {
            "location": "Oslo, Norway",
            "price_min": 250000,
            "price_max": 450000,
            "beds_min": 2,
            "keywords": ["balcony", "near tram"],
        }
    ],
    guardrails=[
        "Model must not use real-time user location without consent",
        "If user doesn't specify price range, model should ask before searching",
        "Model must inform user of results before suggesting bookings",
    ],
)

GET_LISTING_DETAILS_SPEC = ActionSpec(
    name="get_listing_details",
    description="Get full details for a specific listing",
    category="search",
    requires_confirmation=False,
    external_api=True,
    params_schema={
        "type": "object",
        "properties": {
            "listing_id": {"type": "string", "description": "Listing ID"},
        },
        "required": ["listing_id"],
    },
    guardrails=[
        "Model should only call this after user shows interest",
    ],
)

BOOK_VIEWING_SPEC = ActionSpec(
    name="book_viewing",
    description="Book a property viewing",
    category="booking",
    requires_confirmation=True,
    external_api=True,
    timeout_seconds=30,
    params_schema={
        "type": "object",
        "properties": {
            "listing_id": {"type": "string"},
            "user_id": {"type": "string"},
            "preferred_windows": {
                "type": "array",
                "items": {"type": "string", "format": "datetime-interval"},
                "description": "ISO 8601 datetime ranges (e.g., 2026-02-01T17:00/2026-02-01T19:00)",
            },
            "notes": {"type": "string", "description": "Additional notes for agent"},
        },
        "required": ["listing_id", "user_id", "preferred_windows"],
    },
    guardrails=[
        "CRITICAL: Model MUST show preview of booking details to user BEFORE sending this action",
        "Model MUST set requires_user_confirmation=True in metadata",
        "Model MUST wait for client.action.confirm before execution",
        "Model should provide at least 2 alternative time slots",
        "Model must explain cancellation policy to user",
    ],
)

# ============================================================================
# CV/DOCUMENT ACTIONS
# ============================================================================

CREATE_OR_UPDATE_CV_SPEC = ActionSpec(
    name="create_or_update_cv",
    description="Create or update user's CV",
    category="create",
    requires_confirmation=False,
    external_api=False,
    params_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "cv_payload": {
                "type": "object",
                "properties": {
                    "personal": {"type": "object"},
                    "summary": {"type": "string"},
                    "experience": {"type": "array"},
                    "education": {"type": "array"},
                    "skills": {"type": "array"},
                    "projects": {"type": "array"},
                },
            },
            "format": {
                "type": "array",
                "items": {"type": "string", "enum": ["pdf", "docx", "json"]},
            },
        },
        "required": ["user_id", "cv_payload", "format"],
    },
    guardrails=[
        "Model should show draft/preview before finalizing",
        "Model must preserve existing data unless explicitly updated by user",
    ],
)

# ============================================================================
# LANGUAGE LEARNING ACTIONS
# ============================================================================

SCHEDULE_LESSON_SPEC = ActionSpec(
    name="schedule_lesson",
    description="Schedule a language lesson with tutor",
    category="schedule",
    requires_confirmation=True,
    external_api=False,
    params_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "tutor_id": {"type": "string"},
            "datetime": {"type": "string", "format": "date-time"},
            "duration_minutes": {"type": "integer", "minimum": 15, "maximum": 120},
            "lesson_type": {"type": "string", "enum": ["conversation", "grammar", "prep"]},
        },
        "required": ["user_id", "tutor_id", "datetime", "duration_minutes"],
    },
    guardrails=[
        "Model MUST check user's calendar availability",
        "Model must set requires_user_confirmation=True",
        "Model should not schedule lessons outside normal hours (8 AM - 10 PM user's timezone)",
    ],
)

RECORD_PRACTICE_SPEC = ActionSpec(
    name="record_practice",
    description="Record a practice session (language tutor mode)",
    category="create",
    requires_confirmation=False,
    external_api=False,
    params_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "lesson_id": {"type": "string"},
            "duration_seconds": {"type": "integer"},
            "exercise_type": {"type": "string"},
            "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "feedback": {"type": "string"},
        },
        "required": ["user_id", "lesson_id", "duration_seconds"],
    },
)

# ============================================================================
# NOTIFICATION ACTIONS
# ============================================================================

SEND_EMAIL_SPEC = ActionSpec(
    name="send_email",
    description="Send email notification",
    category="notify",
    requires_confirmation=True,
    external_api=True,
    timeout_seconds=10,
    params_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "format": "email"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "cc": {"type": "array", "items": {"type": "string"}},
            "bcc": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["to", "subject", "body"],
    },
    guardrails=[
        "Model MUST set requires_user_confirmation=True",
        "Model must show exact email content in preview",
        "No marketing/spam emails without explicit user consent",
    ],
)

GENERATE_LEARNING_PLAN_SPEC = ActionSpec(
    name="generate_learning_plan",
    description="Generate a personalized learning plan based on diagnostics and preferences",
    category="create",
    requires_confirmation=False,
    external_api=False,
    timeout_seconds=30,
    params_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "target_language": {"type": "string"},
            "native_language": {"type": "string"},
            "topic": {"type": "string"},
            "session_id": {"type": "string"},
            "estimated_cefr": {"type": "string"},
            "weak_subskills": {"type": "array"},
            "lesson_length": {"type": "integer", "minimum": 5, "maximum": 60},
            "persona_id": {"type": "string"},
        },
        "required": ["user_id", "target_language", "native_language"],
    },
    guardrails=[
        "Model should prefer diagnostic session data when available",
        "If target_language or native_language missing, ask user to уточнить",
    ],
)

START_DIAGNOSTIC_CORE_SPEC = ActionSpec(
    name="start_diagnostic_core",
    description="Start Diagnostic Core flow: portfolio analysis + adaptive diagnostic session + skill matrix",
    category="create",
    requires_confirmation=True,
    external_api=False,
    timeout_seconds=45,
    params_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "native_language": {"type": "string"},
            "target_language": {"type": "string"},
            "portfolio_urls": {"type": "array", "items": {"type": "string"}},
            "portfolio_text": {"type": "string"},
            "projects": {"type": "array"},
            "skills": {"type": "array", "items": {"type": "string"}},
            "start_level_guess": {"type": "string"},
            "use_adaptive": {"type": "boolean"},
            "persona_id": {"type": "string"},
            "optimize_mode": {"type": "boolean"},
            "provider": {"type": "string"},
            "model": {"type": "string"},
        },
        "required": ["user_id", "native_language", "target_language"],
    },
    guardrails=[
        "Model should collect portfolio links or summary before calling",
        "Model should set use_adaptive=true if prior diagnostics exist",
        "Model MUST set requires_user_confirmation=True",
    ],
)

CAREER_UPSKILLING_SPEC = ActionSpec(
    name="career_upskilling",
    description="Analyze skill gaps from CV + monitored jobs and propose upskilling with placement test",
    category="create",
    requires_confirmation=True,
    external_api=False,
    timeout_seconds=45,
    params_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "target_role": {"type": "string"},
            "user_skills": {"type": "array", "items": {"type": "string"}},
            "monitored_jobs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "requirements": {"type": "array", "items": {"type": "string"}},
                        "responsibilities": {"type": "array", "items": {"type": "string"}},
                        "tech_stack": {"type": "array", "items": {"type": "string"}},
                        "required_skills": {"type": "array", "items": {"type": "string"}},
                        "full_description": {"type": "string"},
                    },
                },
            },
            "assessment_mode": {"type": "string", "enum": ["language", "professional"]},
            "target_language": {"type": "string"},
            "native_language": {"type": "string"},
            "start_level_guess": {"type": "string"},
            "use_adaptive": {"type": "boolean"},
            "duration_weeks": {"type": "integer", "minimum": 2, "maximum": 52},
        },
        "required": ["user_id", "monitored_jobs"],
    },
    guardrails=[
        "Model MUST ask for confirmation before starting learning flow",
        "If monitored_jobs missing, ask user to provide desired вакансии",
        "If assessment_mode=language, require target_language and native_language",
    ],
)

SEND_SMS_SPEC = ActionSpec(
    name="send_sms",
    description="Send SMS notification",
    category="notify",
    requires_confirmation=True,
    external_api=True,
    timeout_seconds=10,
    params_schema={
        "type": "object",
        "properties": {
            "phone": {"type": "string", "pattern": r"^\+?[\d\s\-\(\)]+$"},
            "message": {"type": "string", "maxLength": 160},
        },
        "required": ["phone", "message"],
    },
    guardrails=[
        "Model MUST set requires_user_confirmation=True",
        "SMS length limited to 160 chars",
        "Model must include opt-out info",
    ],
)

# ============================================================================
# ACTION REGISTRY
# ============================================================================

ACTION_REGISTRY: Dict[str, ActionSpec] = {
    "search_listings": SEARCH_LISTINGS_SPEC,
    "get_listing_details": GET_LISTING_DETAILS_SPEC,
    "book_viewing": BOOK_VIEWING_SPEC,
    "create_or_update_cv": CREATE_OR_UPDATE_CV_SPEC,
    "schedule_lesson": SCHEDULE_LESSON_SPEC,
    "generate_learning_plan": GENERATE_LEARNING_PLAN_SPEC,
    "start_diagnostic_core": START_DIAGNOSTIC_CORE_SPEC,
    "career_upskilling": CAREER_UPSKILLING_SPEC,
    "record_practice": RECORD_PRACTICE_SPEC,
    "send_email": SEND_EMAIL_SPEC,
    "send_sms": SEND_SMS_SPEC,
}

# Backward compatible alias for legacy imports.
STANDARD_ACTIONS = ACTION_REGISTRY


# ============================================================================
# LLM SYSTEM PROMPT
# ============================================================================

LLM_SYSTEM_PROMPT_REALTIME = """
You are a helpful AI assistant in a real-time conversational system.

## CRITICAL RULES - MODEL BEHAVIOR

1. **NO SIDE-EFFECTS**: You NEVER perform any external actions directly.
   - Instead, you describe your intent via JSON-structured "actions"
   - Actions are executed by the Gateway/Router, NOT by you
   - You receive results back via "action.result" messages

2. **ACTION INVOCATION PATTERN**:
   - When you need to invoke an action, respond with a JSON block:
   ```json
   {
     "type": "model.invoke_action",
     "action": {
       "name": "action_name",
       "id": "act_XXXXX",
       "params": { /* action-specific params */ },
       "metadata": {
         "session_id": "...",
         "user_id": "...",
         "confidence": 0.9,
         "requires_user_confirmation": true/false,
         "audit_tags": ["tag1", "tag2"]
       }
     }
   }
   ```

3. **CONFIRMATION PATTERN**:
   - For actions that modify state (booking, email, scheduling):
     - Set requires_user_confirmation: true
     - ALWAYS show a preview to the user FIRST
     - Wait for client.action.confirm message
     - Do NOT assume confirmation
     - Example: "I'll book this for you. Here's the preview: [details]. Confirm?"

4. **USER EXPERIENCE**:
   - Stream partial responses as you think (model.partial)
   - Be conversational and explain your actions
   - Offer alternatives before taking action
   - Handle failures gracefully (fallback to human-in-loop)

5. **GUARDRAILS**:
   - Maximum 3 booking attempts per session (reset on new session)
   - Maximum 5 emails per session
   - Always include opt-out for communications
   - PII: Hash/redact sensitive data in logs
   - No actions without user context (session_id required)

6. **ERROR HANDLING**:
   - If an action returns status="failed":
     - Apologize and explain error to user
     - Suggest alternatives or ask user to try again
     - Escalate to human if requires_manual_review=true
   - If action times out:
     - Inform user of delay
     - Offer to retry or move to manual booking

## STANDARD ACTIONS YOU CAN INVOKE

Available actions:
- search_listings: Search property listings
- get_listing_details: Get full listing details
- book_viewing: Book a property viewing (requires confirmation)
- create_or_update_cv: Create/update user's CV
- schedule_lesson: Schedule language lesson (requires confirmation)
- record_practice: Record practice session
- send_email: Send email (requires confirmation)
- send_sms: Send SMS (requires confirmation)

Each action has specific parameters - see action definition when invoking.

## EXAMPLES

### Example 1: Searching (no confirmation needed)
User: "Find 2-bed apartments in Oslo under 400k"

You respond with BOTH:
1. Natural language: "I'll search for 2-bed apartments in Oslo under €400,000..."
2. Action invocation:
```json
{
  "type": "model.invoke_action",
  "action": {
    "name": "search_listings",
    "id": "act_search_123",
    "params": {
      "location": "Oslo, Norway",
      "price_max": 400000,
      "beds_min": 2
    },
    "metadata": {
      "session_id": "sess_xyz",
      "confidence": 0.95,
      "requires_user_confirmation": false
    }
  }
}
```

Then await action.result with listings.

### Example 2: Booking (requires confirmation)
User: "Book the first one for next Thursday 5-7pm"

You respond with:
1. Natural language preview: "Great! I found a perfect match. Here are the details..."
2. Action invocation WITH requires_user_confirmation=true:
```json
{
  "type": "model.invoke_action",
  "action": {
    "name": "book_viewing",
    "id": "act_book_456",
    "params": {
      "listing_id": "L123",
      "user_id": "user_xyz",
      "preferred_windows": ["2026-02-05T17:00/2026-02-05T19:00"]
    },
    "metadata": {
      "session_id": "sess_xyz",
      "confidence": 0.88,
      "requires_user_confirmation": true
    }
  }
}
```

Await client.action.confirm before execution.

## CONVERSATION FLOW

1. User sends message (client.message)
2. You generate response:
   - Stream partial responses (model.partial)
   - Invoke actions if needed (model.invoke_action)
   - Provide final response (model.final)
3. You receive action results (action.result)
4. If action requires confirmation:
   - User sends client.action.confirm
   - You proceed or handle rejection
5. Continue conversation

Remember: You are a facilitator, not an executor. Actions happen through the Gateway.
"""


def get_action_spec(action_name: str) -> Optional[ActionSpec]:
    """Look up action specification by name."""
    return ACTION_REGISTRY.get(action_name)


def validate_action_params(action_name: str, params: Dict[str, Any]) -> bool:
    """Validate action parameters against schema."""
    spec = get_action_spec(action_name)
    if not spec:
        return False
    # In production, use jsonschema.validate(params, spec.params_schema)
    return True


def get_all_action_specs() -> List[ActionSpec]:
    """Get all registered action specifications."""
    return list(ACTION_REGISTRY.values())
