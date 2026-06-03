from __future__ import annotations

import json

from app.infrastructure.db.sqlite import DB
from app.services.diagnostic.session import finish_session


def test_finish_session_persists_json_safe_weak_subskills(tmp_path):
    db_path = tmp_path / "diagnostic_finish.db"
    db = DB(str(db_path))
    db.init_schema()

    user_id = "u_diag_finish"
    session_id = "diag_finish_1"

    try:
        db.execute(
            """
            INSERT INTO users (id, email, is_admin, meta_json)
            VALUES (?, ?, 0, '{}')
            """,
            (user_id, "diag.finish@test.dev"),
        )

        db.execute(
            """
            INSERT INTO diagnostic_sessions
            (id, user_id, native_lang, target_lang, start_level_guess, status, seed)
            VALUES (?, ?, 'English', 'Spanish', 'A2', 'running', 123)
            """,
            (session_id, user_id),
        )

        item_payload = {
            "id": "item_1",
            "taskType": "mcq",
            "prompt": "Choose the correct option",
            "answer": {"accepted": ["hola"]},
            "tags": {
                "skill": "grammar",
                "subskill": "verb_conjugation",
                "topic": "present_tense",
                "difficulty": 2.0,
                "taskType": "mcq",
                "cefrBand": "A2",
                "languagePair": "English->Spanish",
            },
        }

        db.execute(
            """
            INSERT INTO diagnostic_session_items
            (session_id, item_id, item_json, order_index, tags_json, item_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                "item_1",
                json.dumps(item_payload),
                0,
                json.dumps(item_payload["tags"]),
                "hash_item_1",
            ),
        )

        db.execute(
            """
            INSERT INTO diagnostic_session_items
            (session_id, item_id, item_json, order_index, tags_json, item_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                "item_2",
                json.dumps(item_payload),
                1,
                json.dumps(item_payload["tags"]),
                "hash_item_2",
            ),
        )

        tags_snapshot = json.dumps(item_payload["tags"])

        db.execute(
            """
            INSERT INTO diagnostic_attempts
            (session_id, item_id, answer_raw, is_correct, score, response_time_ms, tags_snapshot_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, "item_1", "hola", 0, 0.0, 1200, tags_snapshot),
        )

        db.execute(
            """
            INSERT INTO diagnostic_attempts
            (session_id, item_id, answer_raw, is_correct, score, response_time_ms, tags_snapshot_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, "item_2", "adios", 0, 0.0, 900, tags_snapshot),
        )

        results = finish_session(db, session_id)

        assert results["weak_subskills"]

        row = db.fetchone("SELECT matrix_json FROM skill_matrices WHERE user_id = ?", (user_id,))
        assert row is not None

        matrix = json.loads(row["matrix_json"])
        weak_subskills = matrix["diagnostic_results"]["weak_subskills"]

        assert isinstance(weak_subskills, list)
        assert weak_subskills
        assert isinstance(weak_subskills[0], dict)
        assert "suggestedFocus" in weak_subskills[0]
    finally:
        db.close()
