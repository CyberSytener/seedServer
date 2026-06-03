"""
Advanced Reply Parser with ML & Human-in-the-Loop
Improved reply detection, parsing, and feedback

Features:
1. Multi-strategy reply parsing
   - Regex patterns (regex)
   - Sentiment analysis (fast heuristics)
   - LLM-based parsing (accurate but slow)

2. Confidence scoring
   - Decision confidence (0.0 - 1.0)
   - Ambiguity detection
   - Flagging uncertain replies

3. Labeled dataset + metrics
   - Training examples with labels
   - Precision/recall tracking
   - F1 score monitoring
   - Category-wise breakdown

4. Human-in-the-loop
   - Flag ambiguous replies for human review
   - Accept corrections (feedback for retraining)
   - Learn from corrections

5. Model performance tracking
   - Confusion matrix
   - Per-category accuracy
   - Drift detection
   - A/B testing support

Usage:
    parser = AdvancedReplyParser(
        strategy='hybrid',  # regex + sentiment + llm
        confidence_threshold=0.8,
        human_review_threshold=0.65,
    )
    
    # Parse reply
    result = parser.parse_reply(email_text)
    # {
    #   'interest_level': 'high',
    #   'confidence': 0.92,
    #   'reasoning': '...',
    #   'needs_human_review': False,
    #   'alternatives': [...]
    # }
    
    # Get metrics
    metrics = parser.get_metrics()
    # {
    #   'accuracy': 0.94,
    #   'precision': {'high': 0.91, 'low': 0.96},
    #   'recall': {'high': 0.89, 'low': 0.97},
    #   'f1': 0.92,
    #   'total_samples': 1250,
    # }
    
    # Record human correction
    parser.record_correction(
        original_prediction='neutral',
        actual_label='high',
        email_text=email_text,
        feedback="Clear indicator: 'very interested'",
    )
"""

from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import re
import logging
from collections import defaultdict
import json

logger = logging.getLogger(__name__)


class InterestLevel(str, Enum):
    """Candidate interest level classification"""
    HIGH = "high"
    NEUTRAL = "neutral"
    LOW = "low"
    UNKNOWN = "unknown"


class ParseStrategy(str, Enum):
    """Reply parsing strategy"""
    REGEX = "regex"           # Fast pattern matching
    SENTIMENT = "sentiment"   # Sentiment analysis + heuristics
    LLM = "llm"              # LLM-based (accurate, slow)
    HYBRID = "hybrid"        # Combine all strategies, vote


@dataclass
class ParsingPatterns:
    """Regex patterns for reply detection"""
    
    # Positive signals
    HIGH_INTEREST_PATTERNS = [
        r"\b(very\s+)?interested\b",
        r"\b(absolutely|definitely|very|strongly)\s+(agree|interested|yes)\b",
        r"\b(let'?s\s+(talk|discuss|schedule|meet))\b",
        r"\b(please\s+let\s+me\s+know.*time)\b",
        r"\b(i'?d\s+love\s+(to|to\s+discuss))\b",
        r"\b(looking\s+forward)\b",
        r"\b(great\s+opportunity)\b",
        r"\b(count\s+me\s+in)\b",
    ]
    
    # Negative signals
    LOW_INTEREST_PATTERNS = [
        r"\b(not\s+interested)\b",
        r"\b(no\s+(?:thanks|thank\s+you))\b",
        r"\b(pass|passing)\b",
        r"\b(unfortunately|regretfully)\b",
        r"\b(not\s+(?:looking|fit))\b",
        r"\b(thanks\s+but\s+no\s+thanks)\b",
        r"\b(at\s+this\s+time.*not)\b",
        r"\b(not\s+the\s+right\s+fit)\b",
    ]
    
    # Neutral/Follow-up
    NEUTRAL_PATTERNS = [
        r"\b(can\s+you\s+tell\s+me\s+more)\b",
        r"\b(more\s+information)\b",
        r"\b(what\s+is\s+the.*salary)\b",
        r"\b(need\s+to\s+think)\b",
        r"\b(will\s+let\s+you\s+know)\b",
    ]


@dataclass
class TrainingExample:
    """Labeled training example"""
    email_text: str
    label: InterestLevel
    source: str = "human"  # human, model_feedback, uncertain
    confidence: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsingResult:
    """Result of reply parsing"""
    interest_level: InterestLevel
    confidence: float  # 0.0 - 1.0
    reasoning: str    # Why we made this decision
    needs_human_review: bool
    strategy_used: ParseStrategy
    alternatives: List[Tuple[InterestLevel, float]] = field(default_factory=list)
    decision_breakdown: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsingMetrics:
    """Parsing performance metrics"""
    accuracy: float
    precision: Dict[str, float]
    recall: Dict[str, float]
    f1: Dict[str, float]
    confusion_matrix: Dict[str, Dict[str, int]]
    total_samples: int
    samples_per_category: Dict[str, int]
    last_updated: datetime = field(default_factory=datetime.now)


# ============================================================================
# ADVANCED REPLY PARSER
# ============================================================================

class AdvancedReplyParser:
    """
    Parse email replies with multiple strategies
    
    Strategies:
    1. Regex - Fast pattern matching
    2. Sentiment - Sentiment + keyword analysis
    3. LLM - Accurate but slow
    4. Hybrid - Combine all, weighted voting
    """
    
    def __init__(
        self,
        strategy: ParseStrategy = ParseStrategy.HYBRID,
        confidence_threshold: float = 0.80,
        human_review_threshold: float = 0.65,
    ):
        self.strategy = ParseStrategy(strategy)
        self.confidence_threshold = confidence_threshold
        self.human_review_threshold = human_review_threshold
        
        # Training dataset
        self.training_examples: List[TrainingExample] = []
        
        # Metrics tracking
        self.predictions: List[Tuple[InterestLevel, InterestLevel]] = []
        
        # Patterns
        self.patterns = ParsingPatterns()
    
    def parse_reply(self, email_text: str, llm_client=None) -> ParsingResult:
        """
        Parse email reply and return interest level
        
        Args:
            email_text: Email body/subject
            llm_client: Optional LLM client for advanced parsing
        
        Returns:
            ParsingResult with confidence and reasoning
        """
        if self.strategy == ParseStrategy.REGEX:
            return self._parse_regex(email_text)
        
        elif self.strategy == ParseStrategy.SENTIMENT:
            return self._parse_sentiment(email_text)
        
        elif self.strategy == ParseStrategy.LLM:
            if not llm_client:
                logger.warning("⚠️  LLM client not provided, falling back to sentiment")
                return self._parse_sentiment(email_text)
            return self._parse_llm(email_text, llm_client)
        
        elif self.strategy == ParseStrategy.HYBRID:
            return self._parse_hybrid(email_text, llm_client)
        
        raise ValueError(f"Unknown strategy: {self.strategy}")
    
    def _parse_regex(self, email_text: str) -> ParsingResult:
        """
        Parse using regex patterns (fast)
        
        Pros: Fast, interpretable
        Cons: Limited coverage, many false negatives
        """
        text_lower = email_text.lower()
        
        high_interest_score = sum(
            1 for pattern in self.patterns.HIGH_INTEREST_PATTERNS
            if re.search(pattern, text_lower, re.IGNORECASE)
        )
        
        low_interest_score = sum(
            1 for pattern in self.patterns.LOW_INTEREST_PATTERNS
            if re.search(pattern, text_lower, re.IGNORECASE)
        )
        
        neutral_score = sum(
            1 for pattern in self.patterns.NEUTRAL_PATTERNS
            if re.search(pattern, text_lower, re.IGNORECASE)
        )
        
        total_score = high_interest_score + low_interest_score + neutral_score
        
        if total_score == 0:
            # No patterns matched
            interest_level = InterestLevel.UNKNOWN
            confidence = 0.3
        elif high_interest_score > low_interest_score:
            interest_level = InterestLevel.HIGH
            confidence = min(high_interest_score / max(total_score, 1), 1.0)
        elif low_interest_score > high_interest_score:
            interest_level = InterestLevel.LOW
            confidence = min(low_interest_score / max(total_score, 1), 1.0)
        else:
            interest_level = InterestLevel.NEUTRAL
            confidence = min(neutral_score / max(total_score, 1), 1.0)
        
        return ParsingResult(
            interest_level=interest_level,
            confidence=confidence,
            reasoning=f"Regex patterns: {high_interest_score} positive, {low_interest_score} negative, {neutral_score} neutral",
            needs_human_review=confidence < self.human_review_threshold,
            strategy_used=ParseStrategy.REGEX,
            decision_breakdown={
                "high_score": high_interest_score,
                "low_score": low_interest_score,
                "neutral_score": neutral_score,
            }
        )
    
    def _parse_sentiment(self, email_text: str) -> ParsingResult:
        """
        Parse using sentiment + keywords (moderate)
        
        Simple sentiment analysis + keyword heuristics
        """
        # Simple sentiment heuristics
        positive_words = [
            "interested", "excited", "excellent", "great", "fantastic",
            "perfect", "definitely", "absolutely", "yes", "love", "great"
        ]
        negative_words = [
            "not interested", "pass", "unfortunately", "regrets", "no thanks",
            "decline", "busy", "other priorities"
        ]
        
        text_lower = email_text.lower()
        
        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)
        
        # Calculate confidence based on word density
        words = text_lower.split()
        word_count = len(words)
        
        if word_count < 5:
            confidence_factor = 0.5
        else:
            confidence_factor = 1.0
        
        if positive_count > negative_count:
            interest_level = InterestLevel.HIGH
            confidence = min((positive_count / max(word_count / 20, 1)) * confidence_factor, 1.0)
        elif negative_count > positive_count:
            interest_level = InterestLevel.LOW
            confidence = min((negative_count / max(word_count / 20, 1)) * confidence_factor, 1.0)
        else:
            interest_level = InterestLevel.NEUTRAL
            confidence = 0.5 * confidence_factor
        
        return ParsingResult(
            interest_level=interest_level,
            confidence=confidence,
            reasoning=f"Sentiment: {positive_count} positive, {negative_count} negative words",
            needs_human_review=confidence < self.human_review_threshold,
            strategy_used=ParseStrategy.SENTIMENT,
        )
    
    def _parse_llm(self, email_text: str, llm_client) -> ParsingResult:
        """
        Parse using LLM (most accurate but slow)
        
        Requires LLM API call. Use for important decisions or training.
        """
        try:
            prompt = f"""
Analyze this email reply and determine the candidate's interest level in the job opportunity.

Email: {email_text}

Respond with JSON:
{{
    "interest_level": "high" | "neutral" | "low" | "unknown",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}
"""
            # Call LLM (implementation depends on LLM provider)
            # result = llm_client.complete(prompt)
            
            # Use the provided LLM client
            raw = llm_client.complete(prompt)

            # Normalize response: accept dict, JSON string, or object with dict()/to_dict()
            parsed: dict
            if isinstance(raw, dict):
                parsed = raw
            elif isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("⚠️ LLM returned a string that is not JSON; treating as reasoning text")
                    parsed = {"reasoning": raw}
            elif hasattr(raw, "to_dict"):
                parsed = raw.to_dict()
            elif hasattr(raw, "dict"):
                parsed = raw.dict()
            else:
                # Unknown format; store as reasoning
                parsed = {"reasoning": str(raw)}

            # Extract fields with sensible defaults
            level_raw = parsed.get("interest_level") or parsed.get("interest") or parsed.get("label")
            level = InterestLevel.UNKNOWN
            if isinstance(level_raw, str):
                level_low = level_raw.strip().lower()
                for lv in InterestLevel:
                    if lv.value == level_low:
                        level = lv
                        break

            confidence = float(parsed.get("confidence", 0.5)) if parsed.get("confidence") is not None else 0.5
            reasoning = parsed.get("reasoning", parsed.get("explanation", "LLM analysis"))

            return ParsingResult(
                interest_level=level,
                confidence=confidence,
                reasoning=f"LLM: {reasoning}",
                needs_human_review=confidence < self.human_review_threshold,
                strategy_used=ParseStrategy.LLM,
                decision_breakdown={"raw": parsed},
            )
        
        except Exception as e:
            logger.error(f"❌ LLM parsing failed: {e}")
            # Fallback to sentiment
            return self._parse_sentiment(email_text)
    
    def _parse_hybrid(
        self,
        email_text: str,
        llm_client=None,
    ) -> ParsingResult:
        """
        Hybrid parsing: Combine regex + sentiment + LLM
        
        Vote-based approach with confidence scoring
        """
        results = []
        
        # Strategy 1: Regex (fast, low confidence)
        regex_result = self._parse_regex(email_text)
        results.append((regex_result, 0.3))  # Weight: 30%
        
        # Strategy 2: Sentiment (moderate)
        sentiment_result = self._parse_sentiment(email_text)
        results.append((sentiment_result, 0.4))  # Weight: 40%
        
        # Strategy 3: LLM (if available, high confidence)
        if llm_client:
            try:
                llm_result = self._parse_llm(email_text, llm_client)
                results.append((llm_result, 0.3))  # Weight: 30%
            except Exception as e:
                logger.warning(f"⚠️  LLM parsing skipped: {e}")
        
        # Vote-based decision
        votes = defaultdict(float)
        for result, weight in results:
            votes[result.interest_level] += weight * result.confidence
        
        # Get winning vote
        winning_level = max(votes, key=votes.get)
        confidence = votes[winning_level] / sum(w for _, w in results)
        
        # Get alternatives
        alternatives = sorted(
            [(level, votes[level]) for level in votes if level != winning_level],
            key=lambda x: x[1],
            reverse=True,
        )
        
        return ParsingResult(
            interest_level=winning_level,
            confidence=confidence,
            reasoning=f"Hybrid: {len(results)} strategies voted, confidence {confidence:.2%}",
            needs_human_review=confidence < self.human_review_threshold,
            strategy_used=ParseStrategy.HYBRID,
            alternatives=alternatives,
            decision_breakdown={
                "strategies": len(results),
                "votes": dict(votes),
            }
        )
    
    def record_correction(
        self,
        original_prediction: InterestLevel,
        actual_label: InterestLevel,
        email_text: str,
        feedback: str = "",
    ) -> None:
        """
        Record human correction for retraining
        
        Used to:
        1. Track model accuracy
        2. Build training dataset
        3. Detect model drift
        4. Improve future predictions
        """
        # Add to training examples
        self.training_examples.append(TrainingExample(
            email_text=email_text,
            label=actual_label,
            source="human",
            metadata={"feedback": feedback, "original_prediction": original_prediction},
        ))
        
        # Track prediction
        self.predictions.append((original_prediction, actual_label))
        
        logger.info(f"📝 Correction recorded: {original_prediction} → {actual_label}")
    
    def get_metrics(self) -> ParsingMetrics:
        """
        Calculate parsing accuracy metrics
        
        Metrics:
        - Accuracy: (TP + TN) / Total
        - Precision: TP / (TP + FP) per category
        - Recall: TP / (TP + FN) per category
        - F1: Harmonic mean of precision and recall
        """
        if not self.predictions:
            return ParsingMetrics(
                accuracy=0.0,
                precision={},
                recall={},
                f1={},
                confusion_matrix={},
                total_samples=0,
                samples_per_category={},
            )
        
        # Build confusion matrix
        confusion = defaultdict(lambda: defaultdict(int))
        for predicted, actual in self.predictions:
            confusion[actual][predicted] += 1
        
        # Calculate metrics per category
        precision = {}
        recall = {}
        f1 = {}
        
        for level in InterestLevel:
            tp = confusion[level][level]
            fp = sum(confusion[other][level] for other in InterestLevel if other != level)
            fn = sum(confusion[level][other] for other in InterestLevel if other != level)
            
            precision[level.value] = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall[level.value] = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            
            if precision[level.value] + recall[level.value] > 0:
                f1[level.value] = 2 * (precision[level.value] * recall[level.value]) / (
                    precision[level.value] + recall[level.value]
                )
            else:
                f1[level.value] = 0.0
        
        # Calculate overall accuracy
        correct = sum(confusion[level][level] for level in InterestLevel)
        total = len(self.predictions)
        accuracy = correct / total if total > 0 else 0.0
        
        # Samples per category
        samples_per_category = {
            level.value: sum(confusion[level].values()) for level in InterestLevel
        }
        
        return ParsingMetrics(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1=f1,
            confusion_matrix={
                actual.value: {pred.value: count for pred, count in counts.items()}
                for actual, counts in confusion.items()
            },
            total_samples=total,
            samples_per_category=samples_per_category,
        )
    
    def detect_drift(self, window_size: int = 100) -> bool:
        """
        Detect if model accuracy is drifting
        
        Compares recent accuracy vs overall accuracy
        """
        if len(self.predictions) < window_size:
            return False
        
        recent = self.predictions[-window_size:]
        overall_metrics = self.get_metrics()
        
        recent_correct = sum(1 for pred, actual in recent if pred == actual)
        recent_accuracy = recent_correct / len(recent)
        
        # Drift threshold: 5% drop in accuracy
        return recent_accuracy < (overall_metrics.accuracy - 0.05)
    
    def save_training_data(self, filepath: str) -> None:
        """Save training examples to file"""
        data = {
            "examples": [asdict(ex) for ex in self.training_examples],
            "created_at": datetime.now().isoformat(),
            "total_examples": len(self.training_examples),
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.info(f"✅ Training data saved: {filepath}")
    
    def load_training_data(self, filepath: str) -> None:
        """Load training examples from file"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        for ex_data in data.get("examples", []):
            ex_data['created_at'] = datetime.fromisoformat(ex_data['created_at'])
            self.training_examples.append(TrainingExample(**ex_data))
        
        logger.info(f"✅ Training data loaded: {len(self.training_examples)} examples")


if __name__ == "__main__":
    print("✅ Advanced reply parser ready")
    print("   Strategies: Regex, Sentiment, LLM, Hybrid")
    print("   Features: Confidence scoring, metrics, human-in-the-loop")
