from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple


_BRAND_TOKENS = {
    "tine",
    "q",
    "q-meieriene",
    "meieriene",
    "rema",
    "coop",
    "kiwi",
    "first",
    "price",
    "prior",
    "gilde",
    "nora",
    "bama",
    "synnove",
    "synnovefinden",
}

_ALIASES_TO_CANONICAL = {
    "milk": "milk",
    "melk": "milk",
    "moloko": "milk",
    "молоко": "milk",
    "молока": "milk",
    "молоком": "milk",
    "pork": "pork",
    "svin": "pork",
    "svinekjott": "pork",
    "svinekjøtt": "pork",
    "свинина": "pork",
    "свинины": "pork",
    "egg": "eggs",
    "eggs": "eggs",
    "egges": "eggs",
    "eggene": "eggs",
    "яйцо": "eggs",
    "яйца": "eggs",
    "хлеб": "bread",
    "bread": "bread",
    "brod": "bread",
    "brød": "bread",
    "sausage": "grill sausages",
    "sausages": "grill sausages",
    "grill sausage": "grill sausages",
    "grill sausages": "grill sausages",
    "grillpolse": "grill sausages",
    "grillpølse": "grill sausages",
    "polse": "grill sausages",
    "pølse": "grill sausages",
    "sosiski": "grill sausages",
    "сосиски": "grill sausages",
    "гриль колбаски": "grill sausages",
    "chicken": "chicken",
    "kylling": "chicken",
    "курица": "chicken",
    "beef": "beef",
    "говядина": "beef",
    "fish": "fish",
    "рыба": "fish",
    "tomato": "tomatoes",
    "tomatoes": "tomatoes",
    "tomat": "tomatoes",
    "tomater": "tomatoes",
    "помидор": "tomatoes",
    "помидоры": "tomatoes",
    "potato": "potatoes",
    "potatoes": "potatoes",
    "potet": "potatoes",
    "poteter": "potatoes",
    "картофель": "potatoes",
    "картошка": "potatoes",
}

_CATEGORY_HINTS = {
    "Dairy": {"milk", "cheese", "yogurt", "butter", "cream"},
    "Meat": {"pork", "beef", "chicken", "grill sausages", "sausages", "sausage"},
    "Fish": {"fish", "salmon", "tuna", "shrimp"},
    "Vegetables": {"tomatoes", "potatoes", "onion", "carrot", "lettuce", "cucumber", "pepper"},
    "Fruit": {"banana", "apple", "orange", "grape", "pear", "berry", "berries"},
    "Bakery": {"bread", "bun", "roll", "croissant"},
    "Staples (Spices/Oil)": {"rice", "pasta", "flour", "oil", "salt", "sugar", "spice"},
    "Ready Meals": {"ready meal", "salad", "soup", "pizza", "lasagna"},
}

_UNIT_ALIASES = {
    "kg": {"kg", "kilo", "kilogram", "kilograms", "килограмм", "килограмма", "килограммов", "киллограмм", "кг"},
    "g": {"g", "gram", "grams", "гр", "г", "грамм", "грамма", "граммов"},
    "l": {"l", "liter", "litre", "liters", "litres", "л", "литр", "литра", "литров"},
    "ml": {"ml", "milliliter", "millilitre", "milliliters", "millilitres", "мл", "миллилитр", "миллилитра", "миллилитров"},
    "pcs": {"pc", "pcs", "piece", "pieces", "stk", "stk.", "шт", "штука", "штуки", "штук"},
    "pack": {"pack", "packs", "package", "pkg", "пачка", "пачки", "пачек", "упаковка", "упаковки"},
    "bottle": {"bottle", "bottles", "бутылка", "бутылки", "бутылок"},
    "can": {"can", "cans", "банка", "банки", "банок"},
}

_QUANTITY_WORDS = {
    "one": 1.0,
    "a": 1.0,
    "an": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "half": 0.5,
    "en": 1.0,
    "ett": 1.0,
    "to": 2.0,
    "tre": 3.0,
    "fire": 4.0,
    "fem": 5.0,
    "halv": 0.5,
    "один": 1.0,
    "одна": 1.0,
    "одно": 1.0,
    "два": 2.0,
    "две": 2.0,
    "три": 3.0,
    "четыре": 4.0,
    "пять": 5.0,
    "пол": 0.5,
    "половина": 0.5,
}

_FILLER_PATTERN = re.compile(
    r"\b("
    r"add|added|put|store|to|my|the|fridge|inventory|i|ive|i've|just|bought|buy|got|have|had|"
    r"jeg|har|kjopt|kjøpt|la|legg|til|min|mitt|mitten|kjoleskap|kjøleskap|"
    r"я|купил|купила|купили|добавь|добавил|добавила|в|мой|моем|холодильник|инвентарь|у|меня"
    r")\b",
    flags=re.IGNORECASE,
)


def _ascii_fold(value: str) -> str:
    lowered = value.lower()
    replacements = {
        "ø": "o",
        "å": "a",
        "æ": "ae",
        "ö": "o",
        "ä": "a",
        "ü": "u",
    }
    for source, target in replacements.items():
        lowered = lowered.replace(source, target)
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_product_key(value: str) -> str:
    folded = _ascii_fold(str(value or "").strip())
    folded = re.sub(r"[%+/]", " ", folded)
    folded = re.sub(r"[^\w\s\-]", " ", folded, flags=re.UNICODE)
    folded = re.sub(r"\s+", " ", folded).strip()
    return folded


def _category_for_name(canonical_name: str) -> str:
    lowered = normalize_product_key(canonical_name)
    for category, keywords in _CATEGORY_HINTS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "Staples (Spices/Oil)"


def normalize_unit(raw_unit: Any) -> str:
    unit = normalize_product_key(str(raw_unit or ""))
    if not unit:
        return "pcs"
    for canonical, aliases in _UNIT_ALIASES.items():
        if unit in aliases:
            return canonical
    return unit


def _is_known_unit_alias(raw_unit: Any) -> bool:
    unit = normalize_product_key(str(raw_unit or ""))
    if not unit:
        return False
    for aliases in _UNIT_ALIASES.values():
        if unit in aliases:
            return True
    return False


def _try_parse_quantity(token: str) -> Optional[float]:
    if not token:
        return None
    cleaned = token.strip().lower().replace(",", ".")
    if cleaned in _QUANTITY_WORDS:
        return _QUANTITY_WORDS[cleaned]
    try:
        value = float(cleaned)
        if value > 0:
            return value
    except Exception:
        return None
    return None


def normalize_quantity_unit(quantity: Any, unit: Any, *, name: Optional[str] = None) -> Tuple[float, str]:
    qty: Optional[float] = None
    try:
        if quantity is not None and str(quantity).strip() != "":
            parsed = float(quantity)
            if parsed > 0:
                qty = parsed
    except Exception:
        qty = None
    unit_norm = normalize_unit(unit)

    if (unit_norm == "pcs" or not unit_norm) and name:
        lowered = normalize_product_key(name)
        unit_hints = {
            "kg": (" кг", "kg", "kilogram", "килограмм", "киллограмм"),
            "g": (" г", "gram", "грамм", "гр"),
            "l": (" л", "liter", "litre", "литр"),
            "ml": (" мл", "milliliter", "миллилитр"),
        }
        for canonical, hints in unit_hints.items():
            if any(hint in lowered for hint in hints):
                unit_norm = canonical
                break

    if qty is None:
        qty = 1.0

    if qty <= 0:
        qty = 1.0

    if not unit_norm:
        unit_norm = "pcs"

    return float(qty), unit_norm


def canonicalize_product(name: Any, *, brand: Optional[str] = None, preferred_language: str = "en") -> Dict[str, Optional[str]]:
    raw_name = str(name or "").strip()
    if not raw_name:
        return {
            "canonical_name": None,
            "display_name": None,
            "category": None,
            "brand": str(brand or "").strip() or None,
            "normalized_key": "",
            "product_id": None,
        }

    original_folded = normalize_product_key(raw_name)
    tokens = [token for token in original_folded.split(" ") if token]

    brand_folded = normalize_product_key(str(brand or ""))
    brand_tokens = {token for token in brand_folded.split(" ") if token}
    if not brand_tokens:
        brand_tokens = set()

    cleaned_tokens: List[str] = []
    for token in tokens:
        if token in _BRAND_TOKENS or token in brand_tokens:
            continue
        if re.fullmatch(r"\d+([.,]\d+)?", token):
            continue
        if token in {"x", "xl", "xxl", "small", "large", "stor", "liten"}:
            continue
        cleaned_tokens.append(token)

    cleaned_name = " ".join(cleaned_tokens).strip() or original_folded

    canonical_name = _ALIASES_TO_CANONICAL.get(cleaned_name)
    if not canonical_name:
        for alias, canonical in sorted(_ALIASES_TO_CANONICAL.items(), key=lambda pair: len(pair[0]), reverse=True):
            if re.search(rf"(^|\s){re.escape(alias)}($|\s)", cleaned_name):
                canonical_name = canonical
                break

    if not canonical_name:
        canonical_name = cleaned_name
        if canonical_name.endswith("es") and canonical_name[:-2] in _ALIASES_TO_CANONICAL:
            canonical_name = _ALIASES_TO_CANONICAL[canonical_name[:-2]]
        elif canonical_name.endswith("s") and canonical_name[:-1] in _ALIASES_TO_CANONICAL:
            canonical_name = _ALIASES_TO_CANONICAL[canonical_name[:-1]]

    canonical_name = re.sub(r"\s+", " ", canonical_name).strip().lower()
    if not canonical_name:
        canonical_name = re.sub(r"\s+", " ", raw_name).strip().lower()

    category = _category_for_name(canonical_name)
    if preferred_language.lower().startswith("en"):
        display_name = canonical_name
    else:
        display_name = canonical_name

    resolved_brand = str(brand or "").strip() or None
    product_id = hashlib.sha1(f"canon|{canonical_name}".encode("utf-8")).hexdigest()[:20]

    return {
        "canonical_name": canonical_name,
        "display_name": display_name,
        "category": category,
        "brand": resolved_brand,
        "normalized_key": normalize_product_key(canonical_name),
        "product_id": product_id,
    }


def extract_items_from_message(message: str) -> List[Dict[str, Any]]:
    text = str(message or "").strip()
    if not text:
        return []

    cleaned = _FILLER_PATTERN.sub(" ", text)
    cleaned = re.sub(r"[;|]", ",", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []

    segments = [
        chunk.strip()
        for chunk in re.split(r",|\band\b|\bog\b|\bи\b|&", cleaned, flags=re.IGNORECASE)
        if chunk and chunk.strip()
    ]

    merged: Dict[str, Dict[str, Any]] = {}

    for segment in segments:
        work = segment.strip()
        if not work:
            continue

        tokens = [token for token in re.split(r"\s+", work) if token]
        if not tokens:
            continue

        qty: Optional[float] = None
        unit = "pcs"
        consumed = 0

        first = tokens[0].lower()
        compact = re.match(r"^(?P<qty>\d+(?:[.,]\d+)?)(?P<unit>[^\d\s]+)$", first)
        if compact:
            qty = _try_parse_quantity(compact.group("qty"))
            if _is_known_unit_alias(compact.group("unit")):
                unit = normalize_unit(compact.group("unit"))
                consumed = 1
        else:
            qty = _try_parse_quantity(first)
            if qty is not None:
                consumed = 1
                if len(tokens) > 1:
                    if _is_known_unit_alias(tokens[1]):
                        possible_unit = normalize_unit(tokens[1])
                        unit = possible_unit
                        consumed = 2
            else:
                if _is_known_unit_alias(first):
                    possible_unit = normalize_unit(first)
                    qty = 1.0
                    unit = possible_unit
                    consumed = 1

        if qty is None:
            qty = 1.0

        name_tokens = tokens[consumed:] if consumed < len(tokens) else []
        name = " ".join(name_tokens).strip()
        if not name:
            continue

        canonical = canonicalize_product(name)
        canonical_name = str(canonical.get("canonical_name") or "").strip()
        display_name = str(canonical.get("display_name") or canonical_name or name).strip()
        if not display_name:
            continue

        normalized_qty, normalized_unit = normalize_quantity_unit(qty, unit, name=display_name)
        dedupe_key = f"{canonical_name or normalize_product_key(display_name)}::{normalized_unit}"
        current = merged.get(dedupe_key)

        if current:
            current["quantity"] = float(current.get("quantity") or 0.0) + normalized_qty
            continue

        merged[dedupe_key] = {
            "name": display_name,
            "canonical_name": canonical_name or normalize_product_key(display_name),
            "original_name": name,
            "quantity": normalized_qty,
            "unit": normalized_unit,
            "expiry_date": None,
            "confidence": 0.82,
            "category": canonical.get("category"),
            "display_name": display_name,
        }

    return list(merged.values())
