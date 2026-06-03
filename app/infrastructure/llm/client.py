"""
Async LLM Client with Connection Pooling

This module provides high-performance async LLM clients with:
- Connection pooling for reduced latency
- Streaming support for progressive delivery
- Timeout and retry handling
- Rate limiting and backoff
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional

import httpx

from app.settings import Settings, get_settings
from .monitoring.metrics import LLMMetrics, MetricContext


logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """LLM provider error"""
    pass


def _stub_generate_text(system_prompt: str, user_prompt: str) -> tuple[str, str]:
    """Generate a simple deterministic stub response text and model name.
    Tries to infer expected JSON shape from the system_prompt first (most reliable),
    then falls back to user_prompt analysis.
    """
    up = user_prompt.lower()
    sp = system_prompt.lower()
    model_used = "stub-1.0"
    
    # **PRIORITY 1: Check system_prompt (most reliable indicator)**
    
    # Exercise/task designer (topic-aware deterministic variants to avoid identical outputs)
    if "exercise designer" in sp or "assessment designer" in sp or "task designer" in sp:
        topic = "general"
        if "topic:" in up:
            try:
                topic = up.split("topic:", 1)[1].split("\n", 1)[0].strip()
            except Exception:
                topic = "general"

        # Three simple deterministic variants keyed by topic
        def tasks_for(topic_key: str):
            if "greet" in topic_key:
                return [
                    {"type": "role_play", "instruction": "Greet and ask how someone is.", "sample_answer": "Hi! How are you? I'm good, thanks."},
                    {"type": "fill_gap", "instruction": "Complete: '___ morning! Nice to see you.'", "sample_answer": "Good"},
                    {"type": "match", "instruction": "Match greeting to response: 'Nice to meet you' → 'Nice to meet you, too.'", "sample_answer": "Nice to meet you -> Nice to meet you, too."},
                    {"type": "translate", "instruction": "Translate: 'Good evening' to Spanish.", "sample_answer": "Buenas noches."},
                    {"type": "listening", "instruction": "Choose the best reply to 'How's it going?'", "sample_answer": "Pretty good, thanks."}
                ]
            if "introduc" in topic_key:
                return [
                    {"type": "role_play", "instruction": "Introduce yourself with name and city.", "sample_answer": "Hi, I'm Sara from Madrid."},
                    {"type": "fill_gap", "instruction": "Complete: 'Let me ___ myself.'", "sample_answer": "introduce"},
                    {"type": "match", "instruction": "Match question to answer: 'Where are you from?' → 'I'm from Lima.'", "sample_answer": "Where are you from? -> I'm from Lima."},
                    {"type": "translate", "instruction": "Translate: 'This is my colleague Ana.'", "sample_answer": "Это моя коллега Ана."},
                    {"type": "listening", "instruction": "Pick the best opener for a self-intro.", "sample_answer": "Hi everyone, I'm Carlos."}
                ]
            if "small talk" in topic_key:
                return [
                    {"type": "role_play", "instruction": "Start small talk about weather.", "sample_answer": "Nice day today, isn't it?"},
                    {"type": "fill_gap", "instruction": "Complete: 'Do you ___ this café often?'", "sample_answer": "come to"},
                    {"type": "match", "instruction": "Match topic to follow-up: 'hobbies' → 'What do you like to do on weekends?'", "sample_answer": "hobbies -> What do you like to do on weekends?"},
                    {"type": "translate", "instruction": "Translate: 'How was your weekend?'", "sample_answer": "Как прошли выходные?"},
                    {"type": "listening", "instruction": "Choose a polite way to end small talk.", "sample_answer": "Great chatting, see you soon!"}
                ]
            # default
            return [
                {"type": "role_play", "instruction": "Role-play a short dialogue on the topic.", "sample_answer": "Hi!"},
                {"type": "fill_gap", "instruction": "Complete a key phrase for the topic.", "sample_answer": "sample"},
                {"type": "match", "instruction": "Match phrase to response.", "sample_answer": "A->B"},
                {"type": "translate", "instruction": "Translate a core phrase.", "sample_answer": "translation"},
                {"type": "listening", "instruction": "Pick best reply.", "sample_answer": "reply"}
            ]

        text = json.dumps({"tasks": tasks_for(topic)}, ensure_ascii=False)
        return text, model_used

    # Validation detection - system prompt is most reliable
    if "rigorous qa reviewer" in sp or "quality assurance" in sp:
        text = json.dumps({
            "valid": True,
            "cefr_appropriate": True,
            "issues": [],
            "score": 92,
            "recommendation": "APPROVE"
        }, ensure_ascii=False)
        return text, model_used
    
    # Content creation detector (creative writer)
    if "creative language-learning content writer" in sp:
        # Check for mode-specific content in user_prompt
        up_lower = user_prompt.lower()
        
        if "learning path mode" in up_lower or "learning_path" in up_lower:
            # Learning Path mode - structured lesson with node/unit
            text = json.dumps({
                "lessonId": f"lesson_{int(time.time())}",
                "mode": "learning_path",
                "targetLang": "Spanish",
                "nativeLang": "English", 
                "level": "A2",
                "topic": "Daily Routines",
                "nodeId": "node_123",
                "unitId": "unit_5",
                "xpReward": 100,
                "exercises": [
                    {
                        "id": "task_1",
                        "type": "mcq",
                        "prompt": "Choose the correct answer",
                        "skill": "vocabulary",
                        "difficulty": 1,
                        "question": "What does 'hola' mean?",
                        "choices": ["Goodbye", "Hello", "Please", "Thank you"],
                        "correctChoiceIndex": 1,
                        "correctAnswer": "Hello",
                        "tip": "This is a basic greeting word"
                    },
                    {
                        "id": "task_2", 
                        "type": "mcq",
                        "prompt": "Choose the correct answer",
                        "skill": "vocabulary",
                        "difficulty": 1,
                        "question": "What does 'adiós' mean?",
                        "choices": ["Hello", "Goodbye", "Please", "Thank you"],
                        "correctChoiceIndex": 1,
                        "correctAnswer": "Goodbye",
                        "tip": "This is a farewell word"
                    },
                    {
                        "id": "task_3",
                        "type": "mcq", 
                        "prompt": "Choose the correct answer",
                        "skill": "grammar",
                        "difficulty": 2,
                        "question": "Complete: Yo ___ estudiante",
                        "choices": ["soy", "eres", "es", "somos"],
                        "correctChoiceIndex": 0,
                        "correctAnswer": "soy",
                        "tip": "Use 'soy' for 'I am' in Spanish"
                    },
                    {
                        "id": "task_4",
                        "type": "translation",
                        "prompt": "Translate to Spanish",
                        "skill": "translation",
                        "difficulty": 2,
                        "sourceText": "Good morning",
                        "targetLang": "Spanish",
                        "correctAnswer": "Buenos días",
                        "acceptedVariants": ["Buen día"],
                        "tip": "This is a common morning greeting"
                    },
                    {
                        "id": "task_5",
                        "type": "translation",
                        "prompt": "Translate to English", 
                        "skill": "translation",
                        "difficulty": 2,
                        "sourceText": "¿Cómo estás?",
                        "targetLang": "English",
                        "correctAnswer": "How are you?",
                        "acceptedVariants": ["How do you do?"],
                        "tip": "This is a common question"
                    },
                    {
                        "id": "task_6",
                        "type": "translation",
                        "prompt": "Translate to Spanish",
                        "skill": "translation", 
                        "difficulty": 3,
                        "sourceText": "I wake up at 7 o'clock",
                        "targetLang": "Spanish",
                        "correctAnswer": "Me despierto a las siete",
                        "acceptedVariants": ["Despierto a las 7"],
                        "tip": "Use present tense for habits"
                    },
                    {
                        "id": "task_7",
                        "type": "word_bank",
                        "prompt": "Arrange the words to form a correct sentence",
                        "skill": "grammar",
                        "difficulty": 2,
                        "words": ["Yo", "estudiar", "español", "quiero"],
                        "correctAnswer": "Yo quiero estudiar español",
                        "tip": "Subject + verb + object word order"
                    },
                    {
                        "id": "task_8", 
                        "type": "word_bank",
                        "prompt": "Arrange the words to form a correct sentence",
                        "skill": "grammar",
                        "difficulty": 3,
                        "words": ["cada", "día", "desayuno", "tomo"],
                        "correctAnswer": "Cada día tomo desayuno",
                        "tip": "Adverb of frequency placement"
                    },
                    {
                        "id": "task_9",
                        "type": "listening_mimic",
                        "prompt": "Listen and repeat",
                        "skill": "pronunciation",
                        "difficulty": 1,
                        "sentence": "Buenos días",
                        "phonetic": "BWEH-nos DEE-as",
                        "tip": "Roll the 'r' sound in días"
                    },
                    {
                        "id": "task_10",
                        "type": "listening_mimic", 
                        "prompt": "Listen and repeat",
                        "skill": "pronunciation",
                        "difficulty": 2,
                        "sentence": "¿Cómo te llamas?",
                        "phonetic": "KOH-mo te YAH-mas",
                        "tip": "The 'll' is pronounced like 'y'"
                    }
                ]
            }, ensure_ascii=False)
            return text, model_used
            
        elif "placement test" in up_lower or "placement_test" in up_lower:
            # Placement Test mode - comprehensive adaptive assessment with full question bank
            questions = [
                # A1 Level (Difficulty 1) - 5 questions
                {
                    "id": "q1",
                    "type": "mcq",
                    "cefrLevel": "A1",
                    "skill": "vocabulary",
                    "difficulty": 1,
                    "question": "What does 'hola' mean?",
                    "choices": ["Goodbye", "Hello", "Please", "Thank you"],
                    "correctChoiceIndex": 1,
                    "correct_answer": "Hello",
                    "discriminationPower": 0.75,
                    "timeEstimateSeconds": 30
                },
                {
                    "id": "q2",
                    "type": "translation", 
                    "cefrLevel": "A1",
                    "skill": "translation",
                    "difficulty": 1,
                    "question": "Translate to Spanish: Hello",
                    "choices": ["Hola", "Adiós", "Por favor", "Gracias"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "Hola",
                    "discriminationPower": 0.72,
                    "timeEstimateSeconds": 45
                },
                {
                    "id": "q3",
                    "type": "mcq",
                    "cefrLevel": "A1", 
                    "skill": "listening",
                    "difficulty": 1,
                    "question": "Choose: Buenos días (Good morning) / Buenas noches (Good night)?",
                    "choices": ["Buenos días", "Buenas noches", "Buenas tardes", "Muy bien"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "Buenos días",
                    "discriminationPower": 0.68,
                    "timeEstimateSeconds": 35
                },
                {
                    "id": "q4",
                    "type": "mcq",
                    "cefrLevel": "A1",
                    "skill": "vocabulary",
                    "difficulty": 1,
                    "question": "What does 'gracias' mean?",
                    "choices": ["Thank you", "Please", "Sorry", "Excuse me"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "Thank you",
                    "discriminationPower": 0.78,
                    "timeEstimateSeconds": 30
                },
                {
                    "id": "q5",
                    "type": "translation",
                    "cefrLevel": "A1",
                    "skill": "translation",
                    "difficulty": 1,
                    "question": "Translate to Spanish: Water",
                    "choices": ["Agua", "Vino", "Café", "Leche"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "Agua",
                    "discriminationPower": 0.70,
                    "timeEstimateSeconds": 40
                },
                # A2 Level (Difficulty 2) - 5 questions
                {
                    "id": "q6",
                    "type": "mcq",
                    "cefrLevel": "A2",
                    "skill": "grammar",
                    "difficulty": 2,
                    "question": "Complete: Yo ___ ingeniero",
                    "choices": ["soy", "eres", "es", "somos"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "soy",
                    "discriminationPower": 0.80,
                    "timeEstimateSeconds": 40
                },
                {
                    "id": "q7",
                    "type": "translation",
                    "cefrLevel": "A2",
                    "skill": "translation",
                    "difficulty": 2,
                    "question": "Translate: I work in an office",
                    "choices": ["Trabajo en una oficina", "Juego en el parque", "Duermo en casa", "Como en restaurante"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "Trabajo en una oficina",
                    "discriminationPower": 0.76,
                    "timeEstimateSeconds": 50
                },
                {
                    "id": "q8",
                    "type": "mcq",
                    "cefrLevel": "A2",
                    "skill": "listening",
                    "difficulty": 2,
                    "question": "What time is mentioned? A) 3:00  B) 6:30  C) 9:15",
                    "choices": ["3:00", "6:30", "9:15", "12:00"],
                    "correctChoiceIndex": 1,
                    "correct_answer": "6:30",
                    "discriminationPower": 0.74,
                    "timeEstimateSeconds": 45
                },
                {
                    "id": "q9",
                    "type": "mcq",
                    "cefrLevel": "A2",
                    "skill": "vocabulary",
                    "difficulty": 2,
                    "question": "Choose the correct word: restaurant in Spanish",
                    "choices": ["restaurante", "teléfono", "mercado", "biblioteca"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "restaurante",
                    "discriminationPower": 0.77,
                    "timeEstimateSeconds": 35
                },
                {
                    "id": "q10",
                    "type": "translation",
                    "cefrLevel": "A2",
                    "skill": "translation",
                    "difficulty": 2,
                    "question": "Translate: Do you like coffee?",
                    "choices": ["¿Te gusta el café?", "¿Tienes hambre?", "¿Dónde está?", "¿Qué hora es?"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "¿Te gusta el café?",
                    "discriminationPower": 0.75,
                    "timeEstimateSeconds": 50
                },
                # B1 Level (Difficulty 3) - 4 questions
                {
                    "id": "q11",
                    "type": "mcq",
                    "cefrLevel": "B1",
                    "skill": "grammar",
                    "difficulty": 3,
                    "question": "Choose the correct subjunctive form: Es importante que ___ estudies mucho",
                    "choices": ["estudios", "estudies", "estudiar", "estudiando"],
                    "correctChoiceIndex": 1,
                    "correct_answer": "estudies",
                    "discriminationPower": 0.82,
                    "timeEstimateSeconds": 50
                },
                {
                    "id": "q12",
                    "type": "translation",
                    "cefrLevel": "B1",
                    "skill": "translation",
                    "difficulty": 3,
                    "question": "Translate: Although he was tired, he continued working",
                    "choices": ["Aunque estaba cansado, seguía trabajando", "Porque estaba cansado, paraba", "Si estaba cansado, dormía", "Cuando estaba cansado, salía"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "Aunque estaba cansado, seguía trabajando",
                    "discriminationPower": 0.79,
                    "timeEstimateSeconds": 60
                },
                {
                    "id": "q13",
                    "type": "mcq",
                    "cefrLevel": "B1",
                    "skill": "listening",
                    "difficulty": 3,
                    "question": "What is the main idea discussed?",
                    "choices": ["Travel benefits", "Climate change", "Technology risks", "Healthcare"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "Travel benefits",
                    "discriminationPower": 0.81,
                    "timeEstimateSeconds": 60
                },
                {
                    "id": "q14",
                    "type": "mcq",
                    "cefrLevel": "B1",
                    "skill": "vocabulary",
                    "difficulty": 3,
                    "question": "Choose the synonym: 'A pesar de las dificultades'",
                    "choices": ["Aunque hay problemas", "Porque hay problemas", "Si hay problemas", "Cuando hay problemas"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "Aunque hay problemas",
                    "discriminationPower": 0.80,
                    "timeEstimateSeconds": 45
                }
            ]
            
            text = json.dumps({
                "testSessionId": f"test_{int(time.time())}",
                "userId": "user_123",
                "targetLang": "Spanish", 
                "nativeLang": "English",
                "maxQuestions": 20,
                "timeLimitSeconds": 1800,
                "questions": questions,
                "adaptiveRules": {
                    "startingDifficulty": 1,
                    "difficultyIncreaseThreshold": 0.8,
                    "difficultyDecreaseThreshold": 0.4,
                    "maxDifficulty": 6,
                    "minDifficulty": 1
                }
            }, ensure_ascii=False)
            return text, model_used
            
        elif "ad hoc" in up_lower or "ad_hoc" in up_lower:
            # Ad-hoc Lesson mode - flexible lesson
            text = json.dumps({
                "lessonId": f"adhoc_{int(time.time())}",
                "mode": "ad_hoc_lesson",
                "targetLang": "Spanish",
                "nativeLang": "English",
                "level": "A2", 
                "topic": "Daily Routines",
                "lessonLength": 10,
                "exercises": [
                    {
                        "id": "task_1",
                        "type": "mcq",
                        "prompt": "Choose the correct answer",
                        "skill": "vocabulary",
                        "difficulty": 1,
                        "question": "What does 'gracias' mean?",
                        "choices": ["Hello", "Goodbye", "Thank you", "Please"],
                        "correctChoiceIndex": 2,
                        "correctAnswer": "Thank you",
                        "tip": "This is a polite expression"
                    },
                    {
                        "id": "task_2",
                        "type": "translation",
                        "prompt": "Translate to Spanish",
                        "skill": "translation",
                        "difficulty": 1,
                        "sourceText": "Good morning",
                        "targetLang": "Spanish",
                        "correctAnswer": "Buenos días",
                        "acceptedVariants": ["Buen día"],
                        "tip": "Morning greeting"
                    },
                    {
                        "id": "task_3",
                        "type": "word_bank",
                        "prompt": "Arrange the words",
                        "skill": "grammar",
                        "difficulty": 1,
                        "words": ["Yo", "soy", "estudiante"],
                        "correctAnswer": "Yo soy estudiante",
                        "tip": "Basic sentence structure"
                    },
                    {
                        "id": "task_4",
                        "type": "listening_mimic",
                        "prompt": "Listen and repeat",
                        "skill": "pronunciation",
                        "difficulty": 1,
                        "sentence": "Hola",
                        "phonetic": "OH-la",
                        "tip": "Basic greeting"
                    },
                    {
                        "id": "task_5",
                        "type": "mcq",
                        "prompt": "Choose the correct answer",
                        "skill": "grammar",
                        "difficulty": 2,
                        "question": "Complete: Tú ___ profesor",
                        "choices": ["soy", "eres", "es", "somos"],
                        "correctChoiceIndex": 1,
                        "correctAnswer": "eres",
                        "tip": "Use 'eres' for 'you are'"
                    },
                    {
                        "id": "task_6",
                        "type": "translation",
                        "prompt": "Translate to English",
                        "skill": "translation",
                        "difficulty": 2,
                        "sourceText": "Me gusta el café",
                        "targetLang": "English",
                        "correctAnswer": "I like coffee",
                        "acceptedVariants": ["I like the coffee"],
                        "tip": "Expressing likes"
                    },
                    {
                        "id": "task_7",
                        "type": "word_bank",
                        "prompt": "Arrange the words",
                        "skill": "grammar",
                        "difficulty": 2,
                        "words": ["cada", "mañana", "despierto", "me"],
                        "correctAnswer": "Cada mañana me despierto",
                        "tip": "Daily routine expression"
                    },
                    {
                        "id": "task_8",
                        "type": "listening_mimic",
                        "prompt": "Listen and repeat",
                        "skill": "pronunciation",
                        "difficulty": 2,
                        "sentence": "¿Cómo estás?",
                        "phonetic": "KOH-mo es-TAHS",
                        "tip": "Question intonation"
                    },
                    {
                        "id": "task_9",
                        "type": "mcq",
                        "prompt": "Choose the correct answer",
                        "skill": "vocabulary",
                        "difficulty": 1,
                        "question": "What does 'por favor' mean?",
                        "choices": ["Excuse me", "Please", "Thank you", "You're welcome"],
                        "correctChoiceIndex": 1,
                        "correctAnswer": "Please",
                        "tip": "Polite request"
                    },
                    {
                        "id": "task_10",
                        "type": "translation",
                        "prompt": "Translate to Spanish",
                        "skill": "translation",
                        "difficulty": 2,
                        "sourceText": "I eat breakfast at 8",
                        "targetLang": "Spanish",
                        "correctAnswer": "Desayuno a las ocho",
                        "acceptedVariants": ["Como desayuno a las 8"],
                        "tip": "Time expressions"
                    }
                ]
            }, ensure_ascii=False)
            return text, model_used
            
        else:
            # Default fallback
            text = json.dumps({
                "intro_story": "Maria starts her day early and makes coffee before work.",
                "exercises": []
            }, ensure_ascii=False)
            return text, model_used
    
    # Curriculum architect (lesson planning)
    if "curriculum architect" in sp or "precise curriculum architect" in sp:
        text = json.dumps({
            "lessonTitle": "Daily Routines (A2)",
            "learningObjectives": [
                "Talk about daily activities",
                "Use present simple for habits",
                "Understand routine-related vocabulary"
            ],
            "grammar_points": ["Present Simple", "Adverbs of frequency"],
            "vocabulary_count": 10,
            "dialogue_scenes": ["Morning at home", "At the office"],
            "exercises_plan": ["fill_in_the_blanks", "matching", "dialogue_practice"]
        }, ensure_ascii=False)
        return text, model_used
    
    # **PRIORITY 2: Fall back to user_prompt analysis**
    
    # Lesson plan detection
    if "lesson plan" in up or "lessontitle" in up or "create a structured lesson plan" in up:
        text = json.dumps({
            "lessonTitle": "Daily Routines (A2)",
            "learningObjectives": [
                "Talk about daily activities",
                "Use present simple for habits",
                "Understand routine-related vocabulary"
            ],
            "grammar_points": ["Present Simple", "Adverbs of frequency"],
            "vocabulary_count": 10,
            "dialogue_scenes": ["Morning at home", "At the office"],
            "exercises_plan": ["fill_in_the_blanks", "matching", "dialogue_practice"]
        }, ensure_ascii=False)
        return text, model_used
    
    # Diagnostic item generation
    if "generate a diagnostic test item" in up:
        text = json.dumps({
            "prompt": "Choose the correct answer: She ____ coffee every morning.",
            "choices": ["drink", "drinks", "drinking", "to drink"],
            "answers": ["drinks"],
            "taskType": "multiple_choice",
            "distractorReasons": {"drink": "verb form incorrect", "drinking": "wrong tense", "to drink": "infinitive not used here"}
        }, ensure_ascii=False)
        return text, model_used
    
    # Fallback minimal JSON
    return json.dumps({"ok": True}, ensure_ascii=False), model_used


@dataclass
class LLMResponse:
    """Complete LLM response"""
    text: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


@dataclass
class LLMStreamChunk:
    """Streaming chunk from LLM"""
    text: str
    is_final: bool
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


class AsyncLLMClient:
    """
    High-performance async LLM client with connection pooling.
    
    Usage:
        async with AsyncLLMClient() as client:
            response = await client.generate(
                system_prompt="You are a helpful tutor",
                user_prompt="Create a lesson about verbs",
                provider="gemini"
            )
    """
    
    def __init__(
        self,
        settings: Optional[Settings] = None,
        max_connections: int = 100,
        max_keepalive_connections: int = 20
    ):
        """
        Initialize async LLM client.
        
        Args:
            settings: App settings (uses defaults if None)
            max_connections: Maximum concurrent connections
            max_keepalive_connections: Keep-alive connection pool size
        """
        self.settings = settings or get_settings()
        self.max_connections = max_connections
        self.max_keepalive_connections = max_keepalive_connections
        self._client: Optional[httpx.AsyncClient] = None
        
    async def __aenter__(self):
        """Context manager entry - creates connection pool"""
        limits = httpx.Limits(
            max_connections=self.max_connections,
            max_keepalive_connections=self.max_keepalive_connections
        )
        
        # Use HTTP/1.1 for stability with Gemini API with higher timeout
        self._client = httpx.AsyncClient(
            limits=limits,
            timeout=httpx.Timeout(180.0, connect=30.0),  # Increased timeout for slower connections
            http2=False  # Use HTTP/1.1 for better stability
        )
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - closes connection pool"""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        provider: str = "gemini",
        model: Optional[str] = None,
        max_tokens: int = 12000,
        timeout_sec: int = 60,
        max_retries: int = 3
    ) -> LLMResponse:
        """
        Generate complete response from LLM with retry logic.
        
        Args:
            system_prompt: System instructions
            user_prompt: User input
            provider: Provider name (gemini, openai)
            model: Model identifier (uses defaults if None)
            max_tokens: Maximum output tokens
            timeout_sec: Request timeout in seconds
            max_retries: Maximum number of retries (default 3)
            
        Returns:
            Complete LLM response with metadata
            
        Raises:
            ProviderError: If request fails after all retries
        """
        if not self._client:
            raise RuntimeError("AsyncLLMClient not initialized - use 'async with'")
        
        import time
        start_time = time.perf_counter()
        last_error = None
        
        # Check if provider is enabled
        if provider == "gemini" and not self.settings.enable_gemini:
            raise ProviderError(f"Provider '{provider}' is disabled")
        elif provider == "openai" and not self.settings.enable_openai:
            raise ProviderError(f"Provider '{provider}' is disabled")
        elif provider == "stub" and not self.settings.enable_stub:
            raise ProviderError(f"Provider '{provider}' is disabled")
        
        if provider == "stub":
            # Synthesize deterministic stub responses for offline/dev use
            text, model_used = _stub_generate_text(system_prompt, user_prompt)
            latency_ms = int(5)
            return LLMResponse(
                text=text,
                provider="stub",
                model=model_used,
                tokens_in=len(user_prompt.split()),
                tokens_out=len(text.split()),
                cost_usd=0.0,
                latency_ms=latency_ms
            )
        
        # Retry logic with exponential backoff
        for attempt in range(max_retries):
            try:
                if provider == "gemini":
                    response = await self._generate_gemini(
                        system_prompt, user_prompt, model, max_tokens, timeout_sec
                    )
                elif provider == "openai":
                    response = await self._generate_openai(
                        system_prompt, user_prompt, model, max_tokens, timeout_sec
                    )
                else:
                    raise ProviderError(f"Unknown provider: {provider}")
                
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                
                # Record success
                model_name = response.get("model", model or provider)
                LLMMetrics.record_api_call(
                    model_name, 
                    latency_ms, 
                    success=True,
                    tokens_used=response.get("tokens_out", 0)
                )
                
                llm_resp = LLMResponse(
                    text=response["text"],
                    provider=provider,
                    model=response["model"],
                    tokens_in=response.get("tokens_in", 0),
                    tokens_out=response.get("tokens_out", 0),
                    cost_usd=response.get("cost_usd", 0.0),
                    latency_ms=latency_ms
                )

                # Attach raw HTTP payload for diagnostics if present
                if isinstance(response, dict) and response.get("raw_json"):
                    try:
                        setattr(llm_resp, "_raw_json", response.get("raw_json"))
                    except Exception:
                        logging.debug("Suppressed exception", exc_info=True)
                return llm_resp
                
            except (ProviderError, asyncio.TimeoutError, httpx.RequestError, httpx.HTTPError) as e:
                last_error = e
                
                if attempt < max_retries - 1:
                    # Exponential backoff: 2^attempt seconds
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"[LLM Retry] {provider} attempt {attempt + 1}/{max_retries} failed: {str(e)}. "
                        f"Retrying in {wait_time}s..."
                    )
                    LLMMetrics.record_retry(provider, attempt + 1, type(e).__name__)
                    await asyncio.sleep(wait_time)
                else:
                    # All retries exhausted
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    LLMMetrics.record_api_call(
                        provider, 
                        latency_ms, 
                        success=False
                    )
                    logger.error(
                        f"[LLM Failed] {provider} failed after {max_retries} attempts: {str(e)}"
                    )
                    raise last_error
    
    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        provider: str = "gemini",
        model: Optional[str] = None,
        max_tokens: int = 12000,
        timeout_sec: int = 60
    ) -> AsyncIterator[LLMStreamChunk]:
        """
        Generate streaming response from LLM for progressive delivery.
        
        Args:
            system_prompt: System instructions
            user_prompt: User input
            provider: Provider name (gemini, openai)
            model: Model identifier
            max_tokens: Maximum output tokens
            timeout_sec: Request timeout
            
        Yields:
            Stream chunks as they arrive
            
        Raises:
            ProviderError: If request fails
        """
        if not self._client:
            raise RuntimeError("AsyncLLMClient not initialized - use 'async with'")
        
        # Check if provider is enabled
        if provider == "gemini" and not self.settings.enable_gemini:
            raise ProviderError(f"Provider '{provider}' is disabled")
        elif provider == "openai" and not self.settings.enable_openai:
            raise ProviderError(f"Provider '{provider}' is disabled")
        elif provider == "stub" and not self.settings.enable_stub:
            raise ProviderError(f"Provider '{provider}' is disabled")
        
        if provider == "gemini":
            async for chunk in self._stream_gemini(
                system_prompt, user_prompt, model, max_tokens, timeout_sec
            ):
                yield chunk
        elif provider == "openai":
            async for chunk in self._stream_openai(
                system_prompt, user_prompt, model, max_tokens, timeout_sec
            ):
                yield chunk
        else:
            raise ProviderError(f"Unknown provider: {provider}")
    
    async def _generate_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str],
        max_tokens: int,
        timeout_sec: int
    ) -> Dict[str, Any]:
        """Generate from Gemini API"""
        api_key = self.settings.gemini_api_key
        if not api_key:
            raise ProviderError("missing GEMINI_API_KEY")
        
        model = model or self.settings.gemini_model_fast or "gemini-2.0-flash-exp"
        url = f"{self.settings.gemini_base_url}/v1beta/models/{model}:generateContent"
        
        payload = {
            "contents": [{"parts": [{"text": user_prompt}], "role": "user"}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        
        try:
            response = await self._client.post(
                f"{url}?key={api_key}",
                json=payload,
                timeout=timeout_sec
            )
            
            if response.status_code >= 400:
                error_text = response.text[:500]
                logger.error(f"Gemini error: {response.status_code} - {error_text}")
                raise ProviderError(f"gemini_http_{response.status_code}: {error_text}")
            
            data = response.json()
            
            # Extract text
            text = ""
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                for part in parts:
                    if isinstance(part.get("text"), str):
                        text += part.get("text")
            
            # Extract token usage
            usage = data.get("usageMetadata", {})
            tokens_in = usage.get("promptTokenCount", 0)
            tokens_out = usage.get("candidatesTokenCount", 0)
            # If text is empty, attach raw response body + headers for diagnostics
            result = {
                "text": text.strip(),
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": 0.0
            }

            if not result["text"]:
                try:
                    raw = {
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "body": data
                    }
                    result["raw_json"] = raw
                except Exception:
                    result["raw_json"] = {"error": "failed to capture raw response"}

            return result
            
        except httpx.TimeoutException as e:
            logger.error(f"Gemini timeout after {timeout_sec}s")
            raise ProviderError(f"gemini_timeout: {str(e)}")
        except httpx.HTTPError as e:
            logger.error(f"Gemini HTTP error: {str(e)}")
            raise ProviderError(f"gemini_error: {str(e)}")
    
    async def _stream_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str],
        max_tokens: int,
        timeout_sec: int
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream from Gemini API"""
        api_key = self.settings.gemini_api_key
        if not api_key:
            raise ProviderError("missing GEMINI_API_KEY")
        
        model = model or self.settings.gemini_model_fast or "gemini-2.0-flash-exp"
        url = f"{self.settings.gemini_base_url}/v1beta/models/{model}:streamGenerateContent"
        
        payload = {
            "contents": [{"parts": [{"text": user_prompt}], "role": "user"}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        
        try:
            async with self._client.stream(
                "POST",
                f"{url}?key={api_key}&alt=sse",
                json=payload,
                timeout=timeout_sec
            ) as response:
                if response.status_code >= 400:
                    error_text = await response.aread()
                    raise ProviderError(f"gemini_http_{response.status_code}: {error_text[:500]}")
                
                accumulated_text = ""
                async for line in response.aiter_lines():
                    if not line.strip() or not line.startswith("data: "):
                        continue
                    
                    data_str = line[6:]  # Remove "data: " prefix
                    if data_str.strip() == "[DONE]":
                        continue
                    
                    try:
                        data = json.loads(data_str)
                        candidates = data.get("candidates", [])
                        if candidates:
                            content = candidates[0].get("content", {})
                            parts = content.get("parts", [])
                            for part in parts:
                                text = part.get("text", "")
                                if text:
                                    accumulated_text += text
                                    yield LLMStreamChunk(text=text, is_final=False)
                        
                        # Check for final chunk with usage
                        usage = data.get("usageMetadata")
                        if usage:
                            yield LLMStreamChunk(
                                text="",
                                is_final=True,
                                tokens_in=usage.get("promptTokenCount"),
                                tokens_out=usage.get("candidatesTokenCount")
                            )
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse SSE data: {data_str}")
                        continue
                
        except httpx.TimeoutException as e:
            raise ProviderError(f"gemini_stream_timeout: {str(e)}")
        except httpx.HTTPError as e:
            raise ProviderError(f"gemini_stream_error: {str(e)}")
    
    async def _generate_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str],
        max_tokens: int,
        timeout_sec: int
    ) -> Dict[str, Any]:
        """Generate from OpenAI API"""
        api_key = self.settings.openai_api_key
        if not api_key:
            raise ProviderError("missing OPENAI_API_KEY")
        
        model = model or "gpt-4"
        url = f"{self.settings.openai_base_url}/v1/chat/completions"
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_tokens
        }
        
        headers = {"Authorization": f"Bearer {api_key}"}
        
        try:
            response = await self._client.post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout_sec
            )
            
            if response.status_code >= 400:
                error_text = response.text[:500]
                raise ProviderError(f"openai_http_{response.status_code}: {error_text}")
            
            data = response.json()
            
            text = ""
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                text = message.get("content", "")
            
            usage = data.get("usage", {})
            
            return {
                "text": text.strip(),
                "model": model,
                "tokens_in": usage.get("prompt_tokens", 0),
                "tokens_out": usage.get("completion_tokens", 0),
                "cost_usd": 0.0
            }
            
        except httpx.TimeoutException as e:
            raise ProviderError(f"openai_timeout: {str(e)}")
        except httpx.HTTPError as e:
            raise ProviderError(f"openai_error: {str(e)}")
    
    async def _stream_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str],
        max_tokens: int,
        timeout_sec: int
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream from OpenAI API"""
        api_key = self.settings.openai_api_key
        if not api_key:
            raise ProviderError("missing OPENAI_API_KEY")
        
        model = model or "gpt-4"
        url = f"{self.settings.openai_base_url}/v1/chat/completions"
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_tokens,
            "stream": True
        }
        
        headers = {"Authorization": f"Bearer {api_key}"}
        
        try:
            async with self._client.stream(
                "POST",
                url,
                json=payload,
                headers=headers,
                timeout=timeout_sec
            ) as response:
                if response.status_code >= 400:
                    error_text = await response.aread()
                    raise ProviderError(f"openai_http_{response.status_code}: {error_text[:500]}")
                
                async for line in response.aiter_lines():
                    if not line.strip() or not line.startswith("data: "):
                        continue
                    
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        yield LLMStreamChunk(text="", is_final=True)
                        break
                    
                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield LLMStreamChunk(text=content, is_final=False)
                    except json.JSONDecodeError:
                        continue
                        
        except httpx.TimeoutException as e:
            raise ProviderError(f"openai_stream_timeout: {str(e)}")
        except httpx.HTTPError as e:
            raise ProviderError(f"openai_stream_error: {str(e)}")


# Singleton client for reuse across requests
_global_client: Optional[AsyncLLMClient] = None
_client_lock = asyncio.Lock()


async def get_llm_client() -> AsyncLLMClient:
    """
    Get or create global async LLM client with connection pooling.
    
    This provides a shared connection pool for optimal performance.
    Call during app startup or use within endpoints.
    """
    global _global_client
    
    async with _client_lock:
        if _global_client is None:
            client = AsyncLLMClient(max_connections=100, max_keepalive_connections=20)
            await client.__aenter__()
            _global_client = client
    
    return _global_client


async def close_llm_client():
    """Close global LLM client (call during app shutdown)"""
    global _global_client
    
    async with _client_lock:
        if _global_client is not None:
            await _global_client.__aexit__(None, None, None)
            _global_client = None
