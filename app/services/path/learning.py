"""
Learning Path System - Helper Functions

Manages user progress through structured learning units and nodes.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.infrastructure.db.sqlite import DB
from app.models.api import (
    UserPath, PathUnit, PathNode,
    NodeStatus, NodeType,
    CompleteNodeResponse
)


def _now_iso() -> str:
    """Get current time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _generate_default_path(target_lang: str, native_lang: str) -> UserPath:
    """
    Generate default learning path with mock units.
    
    In production, this would come from a curriculum database.
    For MVP, we create a simple 3-unit structure.
    """
    units = [
        PathUnit(
            unit_id="unit-1",
            title="Basic Greetings & Introductions",
            progress=0,
            nodes=[
                PathNode(node_id="node-1-1", type=NodeType.lesson, title="Hello & Goodbye", status=NodeStatus.available, xp=15),
                PathNode(node_id="node-1-2", type=NodeType.lesson, title="Nice to Meet You", status=NodeStatus.locked, xp=15),
                PathNode(node_id="node-1-3", type=NodeType.practice, title="Practice: Greetings", status=NodeStatus.locked, xp=10),
            ]
        ),
        PathUnit(
            unit_id="unit-2",
            title="Family & People",
            progress=0,
            nodes=[
                PathNode(node_id="node-2-1", type=NodeType.lesson, title="Family Members", status=NodeStatus.locked, xp=15),
                PathNode(node_id="node-2-2", type=NodeType.lesson, title="Describing People", status=NodeStatus.locked, xp=15),
                PathNode(node_id="node-2-3", type=NodeType.story, title="Story: My Family", status=NodeStatus.locked, xp=20),
            ]
        ),
        PathUnit(
            unit_id="unit-3",
            title="Food & Drinks",
            progress=0,
            nodes=[
                PathNode(node_id="node-3-1", type=NodeType.lesson, title="Common Foods", status=NodeStatus.locked, xp=15),
                PathNode(node_id="node-3-2", type=NodeType.lesson, title="At the Restaurant", status=NodeStatus.locked, xp=15),
                PathNode(node_id="node-3-3", type=NodeType.review, title="Unit Review", status=NodeStatus.locked, xp=25),
            ]
        ),
    ]
    
    return UserPath(
        native_lang=native_lang,
        target_lang=target_lang,
        total_xp=0,
        streak=0,
        cefr_level="A1",
        units=units
    )


def get_or_create_user_path(db: DB, user_id: str, target_lang: str, native_lang: str) -> UserPath:
    """
    Get user's learning path or create default one.
    
    Args:
        db: Database connection
        user_id: User ID
        target_lang: Target language (e.g., "Russian")
        native_lang: Native language (e.g., "English")
        
    Returns:
        UserPath object
    """
    row = db.fetchone(
        "SELECT path_json, total_xp, streak, cefr_level FROM user_paths WHERE user_id = ?",
        (user_id,)
    )
    
    if row:
        # Load existing path
        path_data = json.loads(row["path_json"])
        return UserPath(
            native_lang=native_lang,
            target_lang=target_lang,
            total_xp=row["total_xp"],
            streak=row["streak"],
            cefr_level=row["cefr_level"],
            units=[PathUnit(**unit) for unit in path_data.get("units", [])]
        )
    
    # Create new path
    path = _generate_default_path(target_lang, native_lang)
    
    # Create units and nodes in database
    for unit in path.units:
        # Create unit
        db.execute(
            """
            INSERT INTO units (id, user_id, title, level_tag, status, order_index, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (unit.unit_id, user_id, unit.title, "A1", "locked", path.units.index(unit), _now_iso())
        )
        
        # Create nodes for this unit
        for node in unit.nodes:
            preset_json = json.dumps({
                "type": node.type.value,
                "title": node.title,
                "xp": node.xp
            })
            
            db.execute(
                """
                INSERT INTO nodes (id, unit_id, type, preset_json, status, stars, order_index, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (node.node_id, unit.unit_id, node.type.value, preset_json, 
                 node.status.value, 0, unit.nodes.index(node), _now_iso())
            )
    
    # Save to database
    db.execute(
        """
        INSERT INTO user_paths (user_id, native_lang, target_lang, total_xp, streak, cefr_level, path_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, native_lang, target_lang, path.total_xp, path.streak, path.cefr_level, 
         json.dumps({"units": [u.model_dump(by_alias=True) for u in path.units]}), _now_iso())
    )
    
    return path


def update_node_status(db: DB, user_id: str, node_id: str, status: NodeStatus) -> None:
    """
    Update node status in user's path.
    
    Args:
        db: Database connection
        user_id: User ID
        node_id: Node ID to update
        status: New status
    """
    # Load current path
    row = db.fetchone("SELECT path_json FROM user_paths WHERE user_id = ?", (user_id,))
    if not row:
        return
    
    path_data = json.loads(row["path_json"])
    
    # Update node status
    for unit in path_data.get("units", []):
        for node in unit.get("nodes", []):
            if node["nodeId"] == node_id:
                node["status"] = status.value
                break
    
    # Save updated path
    db.execute(
        "UPDATE user_paths SET path_json = ?, updated_at = ? WHERE user_id = ?",
        (json.dumps(path_data), _now_iso(), user_id)
    )


def complete_node(
    db: DB,
    user_id: str,
    node_id: str,
    unit_id: str,
    score: int,
    lesson_id: Optional[str] = None
) -> CompleteNodeResponse:
    """
    Mark node as completed and update user progress.
    
    Args:
        db: Database connection
        user_id: User ID
        node_id: Node ID
        unit_id: Unit ID
        score: Score (0-100)
        lesson_id: Optional lesson ID
        
    Returns:
        CompleteNodeResponse with updated state
    """
    # Award XP
    xp_awarded = 15
    
    # Check if already completed
    existing = db.fetchone(
        "SELECT id FROM node_completions WHERE user_id = ? AND node_id = ?",
        (user_id, node_id)
    )
    
    if not existing:
        # Create completion record
        completion_id = f"comp_{uuid.uuid4().hex[:12]}"
        db.execute(
            """
            INSERT INTO node_completions (id, user_id, node_id, unit_id, lesson_id, score, xp_awarded, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (completion_id, user_id, node_id, unit_id, lesson_id, score, xp_awarded, _now_iso())
        )
    
    # Update user XP
    db.execute(
        "UPDATE user_paths SET total_xp = total_xp + ?, updated_at = ? WHERE user_id = ?",
        (xp_awarded if not existing else 0, _now_iso(), user_id)
    )
    
    # Update node status to completed
    update_node_status(db, user_id, node_id, NodeStatus.completed)
    
    # Get updated path
    path_row = db.fetchone("SELECT path_json, total_xp FROM user_paths WHERE user_id = ?", (user_id,))
    path_data = json.loads(path_row["path_json"])
    
    # Determine next node and unlock logic
    next_node_id = None
    unlocked_nodes = []
    unlocked_units = []
    
    # Find current unit and node
    for unit_idx, unit in enumerate(path_data.get("units", [])):
        if unit["unitId"] == unit_id:
            nodes = unit["nodes"]
            for node_idx, node in enumerate(nodes):
                if node["nodeId"] == node_id:
                    # Unlock next node in same unit
                    if node_idx + 1 < len(nodes):
                        next_node = nodes[node_idx + 1]
                        if next_node["status"] == "locked":
                            next_node["status"] = "available"
                            next_node_id = next_node["nodeId"]
                            unlocked_nodes.append(next_node_id)
                    
                    # Check if unit is complete
                    all_completed = all(n["status"] == "completed" for n in nodes)
                    if all_completed:
                        # Unlock first node of next unit
                        if unit_idx + 1 < len(path_data["units"]):
                            next_unit = path_data["units"][unit_idx + 1]
                            if next_unit["nodes"] and next_unit["nodes"][0]["status"] == "locked":
                                next_unit["nodes"][0]["status"] = "available"
                                unlocked_units.append(next_unit["unitId"])
                                unlocked_nodes.append(next_unit["nodes"][0]["nodeId"])
                                if not next_node_id:
                                    next_node_id = next_unit["nodes"][0]["nodeId"]
                    
                    break
            break
    
    # Save updated path
    db.execute(
        "UPDATE user_paths SET path_json = ?, updated_at = ? WHERE user_id = ?",
        (json.dumps(path_data), _now_iso(), user_id)
    )
    
    return CompleteNodeResponse(
        node_id=node_id,
        status=NodeStatus.completed,
        xp_awarded=xp_awarded if not existing else 0,
        total_xp=path_row["total_xp"] + (xp_awarded if not existing else 0),
        next_node_id=next_node_id,
        unlocked_nodes=unlocked_nodes,
        unlocked_units=unlocked_units
    )


def get_node_topic(db: DB, user_id: str, node_id: str) -> Optional[str]:
    """
    Get topic for a specific node.
    
    Args:
        db: Database connection
        user_id: User ID
        node_id: Node ID
        
    Returns:
        Topic string or None
    """
    row = db.fetchone("SELECT path_json FROM user_paths WHERE user_id = ?", (user_id,))
    if not row:
        return None
    
    path_data = json.loads(row["path_json"])
    
    for unit in path_data.get("units", []):
        for node in unit.get("nodes", []):
            if node["nodeId"] == node_id:
                # Use node title as topic
                return node.get("title", "General")
    
    return None



