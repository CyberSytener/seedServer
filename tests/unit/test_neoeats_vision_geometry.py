from app.api.inventory_orders_vision_routes import (
    _dedupe_vision_items_for_overlay,
    _extract_vision_geometry,
    _vision_detection_id,
    _vision_icon_key,
)
from app.models.neoeats import VisionDetectedItem


def test_extract_vision_geometry_preserves_bbox_and_center_fields():
    result = _extract_vision_geometry(
        {
            "center_x": "0.42",
            "center_y": 0.58,
            "bbox": {"x": 0.2, "y": "0.3", "width": 0.4, "height": "0.25"},
        }
    )

    assert result == {
        "center_x": 0.42,
        "center_y": 0.58,
        "bbox": {"x": 0.2, "y": 0.3, "width": 0.4, "height": 0.25},
    }


def test_extract_vision_geometry_accepts_nested_center_and_bbox_array():
    result = _extract_vision_geometry(
        {
            "center": {"x": "0.25", "y": "0.75"},
            "bbox": [100, "120", 80, "90"],
        }
    )

    assert result == {
        "center_x": 0.25,
        "center_y": 0.75,
        "bbox": {"x": 100.0, "y": 120.0, "width": 80.0, "height": 90.0},
    }


def test_vision_detected_item_serializes_overlay_geometry():
    item = VisionDetectedItem(
        id="vision-tomato-test",
        detection_id="vision-tomato-test",
        icon_key="vegetable",
        name="Tomato",
        quantity=2,
        unit="pcs",
        confidence=91,
        center_x=0.35,
        center_y=0.45,
        bbox={"x": 0.2, "y": 0.25, "width": 0.3, "height": 0.4},
    )

    payload = item.model_dump()

    assert payload["center_x"] == 0.35
    assert payload["center_y"] == 0.45
    assert payload["bbox"]["width"] == 0.3
    assert payload["detection_id"] == "vision-tomato-test"
    assert payload["icon_key"] == "vegetable"


def test_vision_detection_identity_is_stable_and_unique_by_geometry():
    first = _vision_detection_id(
        canonical_name="tomato",
        display_name="Tomato",
        brand=None,
        geometry={"center_x": 0.25, "center_y": 0.5},
        index=0,
    )
    same = _vision_detection_id(
        canonical_name="tomato",
        display_name="Tomato",
        brand=None,
        geometry={"center_x": 0.25, "center_y": 0.5},
        index=0,
    )
    second = _vision_detection_id(
        canonical_name="tomato",
        display_name="Tomato",
        brand=None,
        geometry={"center_x": 0.75, "center_y": 0.5},
        index=1,
    )

    assert first == same
    assert first != second
    assert first.startswith("vision-tomato-")


def test_vision_icon_key_uses_name_or_category():
    assert _vision_icon_key("whole milk", None) == "dairy"
    assert _vision_icon_key("cheese", None) == "cheese"
    assert _vision_icon_key("chicken breast", None) == "poultry"
    assert _vision_icon_key("potato", None) == "potato"
    assert _vision_icon_key("unknown item", "fruit") == "fruit"
    assert _vision_icon_key("unknown item", None) == "grocery"


def _detected_item(
    name: str,
    *,
    confidence: float = 82,
    bbox: dict[str, float] | None = None,
    center_x: float | None = None,
    center_y: float | None = None,
) -> VisionDetectedItem:
    score = confidence / 100 if confidence > 1 else confidence
    return VisionDetectedItem(
        id=f"vision-{name.lower().replace(' ', '-')}",
        detection_id=f"vision-{name.lower().replace(' ', '-')}",
        icon_key=_vision_icon_key(name, None),
        name=name,
        canonical_name=name.lower(),
        quantity=1,
        unit="pcs",
        confidence=confidence,
        confidence_score=score,
        bbox=bbox,
        center_x=center_x,
        center_y=center_y,
    )


def test_vision_dedupe_collapses_overlapping_duplicate_marker():
    result = _dedupe_vision_items_for_overlay([
        _detected_item("Cheese", confidence=62, bbox={"x": 0.2, "y": 0.2, "width": 0.25, "height": 0.2}),
        _detected_item("Cheese", confidence=88, bbox={"x": 0.22, "y": 0.21, "width": 0.24, "height": 0.19}),
    ])

    assert len(result) == 1
    assert result[0].confidence == 88
    assert result[0].trust_level == "trusted"
    assert result[0].review_required is False
    assert result[0].duplicate_count == 2
    assert result[0].dedupe_key == "cheese||pcs"


def test_vision_dedupe_keeps_same_product_at_separate_positions():
    result = _dedupe_vision_items_for_overlay([
        _detected_item("Tomato", bbox={"x": 0.1, "y": 0.3, "width": 0.16, "height": 0.16}),
        _detected_item("Tomato", bbox={"x": 0.7, "y": 0.3, "width": 0.16, "height": 0.16}),
    ])

    assert len(result) == 2
    assert [item.duplicate_count for item in result] == [None, None]


def test_vision_dedupe_collapses_no_geometry_duplicate_and_marks_review():
    result = _dedupe_vision_items_for_overlay([
        _detected_item("Milk", confidence=64),
        _detected_item("Milk", confidence=63),
    ])

    assert len(result) == 1
    assert result[0].trust_level == "review"
    assert result[0].review_required is True
    assert result[0].duplicate_count == 2
