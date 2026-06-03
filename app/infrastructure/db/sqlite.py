from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable


_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  is_banned INTEGER NOT NULL DEFAULT 0,
  abuse_score INTEGER NOT NULL DEFAULT 0,
  is_admin INTEGER NOT NULL DEFAULT 0,
  api_key_hash TEXT,
  api_key_last4 TEXT,
  api_key_created_at TEXT,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_api_key_hash
  ON users(api_key_hash)
  WHERE api_key_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS plans (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  price_cents_month INTEGER NOT NULL DEFAULT 0,
  fast_daily_limit INTEGER NOT NULL DEFAULT 0,
  actions_per_minute_limit INTEGER NOT NULL DEFAULT 60,
  actions_monthly_limit INTEGER NOT NULL DEFAULT 0,
  post_monthly_delay_sec INTEGER NOT NULL DEFAULT 0,
  batch_priority_base INTEGER NOT NULL DEFAULT 0,
  fast_priority_base INTEGER NOT NULL DEFAULT 0,
  max_input_chars INTEGER NOT NULL DEFAULT 12000,
  max_output_tokens INTEGER NOT NULL DEFAULT 800,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS subscriptions (
  user_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL,
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  meta_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(plan_id) REFERENCES plans(id)
);

CREATE TABLE IF NOT EXISTS usage_daily (
  user_id TEXT NOT NULL,
  day_utc TEXT NOT NULL,
  fast_used INTEGER NOT NULL DEFAULT 0,
  actions_used INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(user_id, day_utc),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS usage_minute (
  user_id TEXT NOT NULL,
  minute_utc TEXT NOT NULL,
  actions_used INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(user_id, minute_utc),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS usage_monthly (
  user_id TEXT NOT NULL,
  month_utc TEXT NOT NULL,
  actions_used INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(user_id, month_utc),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  action TEXT NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  idempotency_key TEXT,
  input_hash TEXT,
  dedup_of_job_id TEXT,
  priority INTEGER NOT NULL DEFAULT 0,
  not_before TEXT,
  queue_name TEXT NOT NULL DEFAULT 'q_batch',
  provider TEXT NOT NULL DEFAULT 'other',
  model TEXT NOT NULL DEFAULT 'unknown',
  persona_id_used TEXT,
  fallback_reason TEXT,
  tokens_in_est INTEGER,
  tokens_out_est INTEGER,
  cost_usd_est REAL,
  tokens_in_actual INTEGER,
  tokens_out_actual INTEGER,
  cost_usd_actual REAL,
  input_text TEXT,
  options_json TEXT NOT NULL DEFAULT '{}',
  result_text TEXT,
  error_code TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  started_at TEXT,
  finished_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(dedup_of_job_id) REFERENCES jobs(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_user_idempotency
  ON jobs(user_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_user_created
  ON jobs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_status_queue
  ON jobs(status, queue_name, priority DESC, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_jobs_not_before
  ON jobs(not_before)
  WHERE not_before IS NOT NULL;

CREATE TABLE IF NOT EXISTS job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  at TEXT NOT NULL DEFAULT (datetime('now')),
  event TEXT NOT NULL,
  data_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_events_job
  ON job_events(job_id, at DESC);

CREATE TABLE IF NOT EXISTS system_state (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lessons (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  lesson_json TEXT NOT NULL,
  persona_id_used TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lessons_user_id ON lessons(user_id);

CREATE TABLE IF NOT EXISTS lesson_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lesson_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  user_answer TEXT NOT NULL,
  correct INTEGER NOT NULL,
  score REAL NOT NULL DEFAULT 0.0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(lesson_id) REFERENCES lessons(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lesson_attempts_lesson_id ON lesson_attempts(lesson_id);

-- Diagnostic Sessions V0
CREATE TABLE IF NOT EXISTS diagnostic_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  native_lang TEXT NOT NULL,
  target_lang TEXT NOT NULL,
  start_level_guess TEXT NOT NULL DEFAULT 'A2',
  status TEXT NOT NULL DEFAULT 'running',
  seed INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_diagnostic_sessions_user_id ON diagnostic_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_diagnostic_sessions_status ON diagnostic_sessions(status);

CREATE TABLE IF NOT EXISTS diagnostic_session_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  item_json TEXT NOT NULL,
  order_index INTEGER NOT NULL,
  tags_json TEXT NOT NULL,
  item_hash TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES diagnostic_sessions(id) ON DELETE CASCADE,
  UNIQUE(session_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_diagnostic_session_items_session_id ON diagnostic_session_items(session_id);
CREATE INDEX IF NOT EXISTS idx_diagnostic_session_items_order ON diagnostic_session_items(session_id, order_index);

CREATE TABLE IF NOT EXISTS diagnostic_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  answer_raw TEXT NOT NULL,
  is_correct INTEGER NOT NULL,
  score REAL NOT NULL DEFAULT 0.0,
  response_time_ms INTEGER,
  tags_snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(session_id) REFERENCES diagnostic_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_diagnostic_attempts_session_id ON diagnostic_attempts(session_id);
CREATE INDEX IF NOT EXISTS idx_diagnostic_attempts_item_id ON diagnostic_attempts(session_id, item_id);

-- Learning Profiles (User Learning Context)
CREATE TABLE IF NOT EXISTS learning_profiles (
  user_id TEXT PRIMARY KEY,
  profile_json TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_learning_profiles_updated_at ON learning_profiles(updated_at DESC);

-- Skill Matrices (Diagnostic Core)
CREATE TABLE IF NOT EXISTS skill_matrices (
  user_id TEXT PRIMARY KEY,
  matrix_json TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  source TEXT NOT NULL DEFAULT 'diagnostic_core',
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_skill_matrices_updated_at ON skill_matrices(updated_at DESC);

-- Bug Reports (Feedback)
CREATE TABLE IF NOT EXISTS bug_reports (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bug_reports_user_id ON bug_reports(user_id);
CREATE INDEX IF NOT EXISTS idx_bug_reports_created_at ON bug_reports(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bug_reports_kind ON bug_reports(kind);

-- Career Learning: Analyses
CREATE TABLE IF NOT EXISTS career_analyses (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  analysis_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_career_analyses_user_id ON career_analyses(user_id);
CREATE INDEX IF NOT EXISTS idx_career_analyses_updated_at ON career_analyses(updated_at DESC);

-- Career Learning: Tracks
CREATE TABLE IF NOT EXISTS career_tracks (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  analysis_id TEXT NOT NULL,
  track_json TEXT NOT NULL,
  progress_percent REAL NOT NULL DEFAULT 0.0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(analysis_id) REFERENCES career_analyses(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_career_tracks_user_id ON career_tracks(user_id);
CREATE INDEX IF NOT EXISTS idx_career_tracks_analysis_id ON career_tracks(analysis_id);
CREATE INDEX IF NOT EXISTS idx_career_tracks_updated_at ON career_tracks(updated_at DESC);

-- Career Learning: Lessons Queue
CREATE TABLE IF NOT EXISTS career_lessons (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  track_id TEXT NOT NULL,
  module_id TEXT NOT NULL,
  lesson_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(track_id) REFERENCES career_tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_career_lessons_user_id ON career_lessons(user_id);
CREATE INDEX IF NOT EXISTS idx_career_lessons_track_id ON career_lessons(track_id);
CREATE INDEX IF NOT EXISTS idx_career_lessons_status ON career_lessons(status);

-- Learning Path Units (Blueprint Pattern - Phase A)
CREATE TABLE IF NOT EXISTS units (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL,
  level_tag TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'locked',
  order_index INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_units_user_id ON units(user_id);
CREATE INDEX IF NOT EXISTS idx_units_user_order ON units(user_id, order_index);
CREATE INDEX IF NOT EXISTS idx_units_status ON units(user_id, status);

-- Learning Path Nodes (Blueprint Pattern - Phase A)
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY,
  unit_id TEXT NOT NULL,
  type TEXT NOT NULL,
  preset_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'locked',
  stars INTEGER NOT NULL DEFAULT 0,
  order_index INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  FOREIGN KEY(unit_id) REFERENCES units(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_nodes_unit_id ON nodes(unit_id);
CREATE INDEX IF NOT EXISTS idx_nodes_unit_order ON nodes(unit_id, order_index);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(unit_id, status);

-- Learning Path Analytics: Node Attempts
CREATE TABLE IF NOT EXISTS node_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  duration_seconds INTEGER,
  tasks_total INTEGER NOT NULL DEFAULT 0,
  tasks_correct INTEGER NOT NULL DEFAULT 0,
  tasks_incorrect INTEGER NOT NULL DEFAULT 0,
  score REAL NOT NULL DEFAULT 0.0,
  success INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE CASCADE,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_node_attempts_node_id ON node_attempts(node_id);
CREATE INDEX IF NOT EXISTS idx_node_attempts_user_id ON node_attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_node_attempts_session_id ON node_attempts(session_id);
CREATE INDEX IF NOT EXISTS idx_node_attempts_completed_at ON node_attempts(completed_at DESC);

-- Learning Path Analytics: Task Attempts (detailed)
CREATE TABLE IF NOT EXISTS task_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_attempt_id INTEGER NOT NULL,
  task_id TEXT NOT NULL,
  task_type TEXT NOT NULL,
  user_answer TEXT NOT NULL,
  correct_answer TEXT NOT NULL,
  is_correct INTEGER NOT NULL,
  response_time_ms INTEGER,
  hint_used INTEGER NOT NULL DEFAULT 0,
  attempts_count INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(node_attempt_id) REFERENCES node_attempts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_attempts_node_attempt_id ON task_attempts(node_attempt_id);
CREATE INDEX IF NOT EXISTS idx_task_attempts_task_id ON task_attempts(task_id);
CREATE INDEX IF NOT EXISTS idx_task_attempts_task_type ON task_attempts(task_type);
CREATE INDEX IF NOT EXISTS idx_task_attempts_is_correct ON task_attempts(is_correct);

-- User Learning Paths (Aggregated State)
CREATE TABLE IF NOT EXISTS user_paths (
  user_id TEXT PRIMARY KEY,
  native_lang TEXT NOT NULL,
  target_lang TEXT NOT NULL,
  total_xp INTEGER NOT NULL DEFAULT 0,
  streak INTEGER NOT NULL DEFAULT 0,
  cefr_level TEXT NOT NULL DEFAULT 'A1',
  path_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_paths_updated_at ON user_paths(updated_at DESC);

-- Node Completions (Simple tracking)
CREATE TABLE IF NOT EXISTS node_completions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  unit_id TEXT NOT NULL,
  lesson_id TEXT,
  score INTEGER NOT NULL DEFAULT 0,
  xp_awarded INTEGER NOT NULL DEFAULT 15,
  completed_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE CASCADE,
  FOREIGN KEY(lesson_id) REFERENCES lessons(id) ON DELETE SET NULL,
  UNIQUE(user_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_node_completions_user_id ON node_completions(user_id);
CREATE INDEX IF NOT EXISTS idx_node_completions_node_id ON node_completions(node_id);
CREATE INDEX IF NOT EXISTS idx_node_completions_completed_at ON node_completions(completed_at DESC);

-- Agent Sessions (Phase 7)
CREATE TABLE IF NOT EXISTS agent_sessions (
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  persona_id TEXT NOT NULL DEFAULT 'seed',
  persona_overrides TEXT NOT NULL DEFAULT '{}',
  budget_config TEXT NOT NULL DEFAULT '{}',
  tool_scopes TEXT NOT NULL DEFAULT '[]',
  pending_confirmations TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  parent_session_id TEXT,
  tenant_id TEXT,
  project_id TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_user_id ON agent_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_parent ON agent_sessions(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_tenant ON agent_sessions(tenant_id);

-- Agent Session Participants (P0-24)
CREATE TABLE IF NOT EXISTS agent_session_participants (
  session_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'viewer',
  tool_scopes TEXT NOT NULL DEFAULT '[]',
  joined_at TEXT NOT NULL DEFAULT (datetime('now')),
  left_at TEXT,
  PRIMARY KEY (session_id, user_id),
  FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_session_participants_user ON agent_session_participants(user_id);

CREATE TABLE IF NOT EXISTS agent_session_messages (
  message_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT,
  tool_name TEXT,
  tool_input TEXT,
  tool_output TEXT,
  budget_snapshot TEXT,
  timestamp TEXT NOT NULL DEFAULT (datetime('now')),
  sender_user_id TEXT,
  FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_session_messages_session_id ON agent_session_messages(session_id, timestamp ASC);
"""

_DB_SINGLETON: "DB | None" = None


def get_db() -> "DB":
  global _DB_SINGLETON
  if _DB_SINGLETON is None:
    db_path = os.getenv("SEED_DB_PATH", "./seed.db")
    _DB_SINGLETON = DB(db_path)
    _DB_SINGLETON.init_schema()
  return _DB_SINGLETON


class DB:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.commit()
            self.apply_migrations()

    def apply_migrations(self) -> None:
        """Best-effort migrations for existing sqlite DBs."""
        with self._lock:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(users)").fetchall()}
            if "is_admin" not in cols:
                self._conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            if "api_key_hash" not in cols:
                self._conn.execute("ALTER TABLE users ADD COLUMN api_key_hash TEXT")
            if "api_key_last4" not in cols:
                self._conn.execute("ALTER TABLE users ADD COLUMN api_key_last4 TEXT")
            if "api_key_created_at" not in cols:
                self._conn.execute("ALTER TABLE users ADD COLUMN api_key_created_at TEXT")

            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_api_key_hash ON users(api_key_hash) WHERE api_key_hash IS NOT NULL"
            )

            pcols = {r[1] for r in self._conn.execute("PRAGMA table_info(plans)").fetchall()}
            if "actions_per_minute_limit" not in pcols:
                self._conn.execute("ALTER TABLE plans ADD COLUMN actions_per_minute_limit INTEGER NOT NULL DEFAULT 60")

            # Persona support migration
            jcols = {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)").fetchall()}
            if "persona_id_used" not in jcols:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN persona_id_used TEXT")
            if "fallback_reason" not in jcols:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN fallback_reason TEXT")

            # Learning Path support in lessons
            lcols = {r[1] for r in self._conn.execute("PRAGMA table_info(lessons)").fetchall()}
            if "node_id" not in lcols:
                self._conn.execute("ALTER TABLE lessons ADD COLUMN node_id TEXT")
            if "unit_id" not in lcols:
                self._conn.execute("ALTER TABLE lessons ADD COLUMN unit_id TEXT")
            if "xp_reward" not in lcols:
                self._conn.execute("ALTER TABLE lessons ADD COLUMN xp_reward INTEGER DEFAULT 15")

            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_minute (
                  user_id TEXT NOT NULL,
                  minute_utc TEXT NOT NULL,
                  actions_used INTEGER NOT NULL DEFAULT 0,
                  PRIMARY KEY(user_id, minute_utc),
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )

            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self):
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def executemany(self, sql: str, seq: Iterable[tuple[Any, ...]]) -> None:
        with self._lock:
            self._conn.executemany(sql, seq)
            self._conn.commit()

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            cur = self._conn.execute(sql, params)
            row = cur.fetchone()
            cur.close()
            return row

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            cur.close()
            return rows


def seed_defaults(db: DB) -> None:
    plans = [
        (
            "free",
            "Free",
            0,
            10,
            30,
            2000,
            300,
            0,
            10,
            12000,
            800,
        ),
        (
            "starter",
            "Starter",
            1200,
            60,
            120,
            12000,
            60,
            20,
            60,
            20000,
            1200,
        ),
        (
            "pro",
            "Pro",
            2500,
            200,
            300,
            40000,
            20,
            60,
            120,
            40000,
            2000,
        ),
    ]

    with db.transaction() as conn:
        conn.executemany(
            """
            INSERT INTO plans(
              id,title,price_cents_month,
              fast_daily_limit,actions_per_minute_limit,actions_monthly_limit,post_monthly_delay_sec,
              batch_priority_base,fast_priority_base,
              max_input_chars,max_output_tokens
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,
              price_cents_month=excluded.price_cents_month,
              fast_daily_limit=excluded.fast_daily_limit,
              actions_per_minute_limit=excluded.actions_per_minute_limit,
              actions_monthly_limit=excluded.actions_monthly_limit,
              post_monthly_delay_sec=excluded.post_monthly_delay_sec,
              batch_priority_base=excluded.batch_priority_base,
              fast_priority_base=excluded.fast_priority_base,
              max_input_chars=excluded.max_input_chars,
              max_output_tokens=excluded.max_output_tokens
            """,
            plans,
        )

        conn.execute(
            """
            INSERT INTO system_state(key,value_json) VALUES('system_mode','{"mode":"normal"}')
            ON CONFLICT(key) DO NOTHING
            """
        )


def get_user_lessons(db: DB, user_id: str) -> list[dict[str, Any]]:
    """Get all lessons for a user with attempt counts."""
    rows = db.fetchall(
        """
        SELECT 
            l.id as lesson_id,
            l.lesson_json,
            l.persona_id_used,
            l.created_at,
            COUNT(DISTINCT la.task_id) as completed_count
        FROM lessons l
        LEFT JOIN lesson_attempts la ON l.id = la.lesson_id AND la.correct = 1
        WHERE l.user_id = ?
        GROUP BY l.id
        ORDER BY l.created_at DESC
        """,
        (user_id,)
    )
    
    return [dict(row) for row in rows]


def get_lesson_by_id(db: DB, lesson_id: str, user_id: str) -> dict[str, Any] | None:
    """Get a specific lesson if it belongs to the user."""
    row = db.fetchone(
        """
        SELECT id, lesson_json, persona_id_used, created_at
        FROM lessons
        WHERE id = ? AND user_id = ?
        """,
        (lesson_id, user_id)
    )
    
    return dict(row) if row else None


def get_lesson_attempts(db: DB, lesson_id: str) -> list[dict[str, Any]]:
    """Get all attempts for a lesson."""
    rows = db.fetchall(
        """
        SELECT task_id, user_answer, correct, score, created_at
        FROM lesson_attempts
        WHERE lesson_id = ?
        ORDER BY created_at ASC
        """,
        (lesson_id,)
    )
    
    return [dict(row) for row in rows]


def delete_lesson(db: DB, lesson_id: str, user_id: str) -> bool:
    """Delete a lesson and its attempts if it belongs to the user."""
    # Check if lesson exists and belongs to user
    lesson = get_lesson_by_id(db, lesson_id, user_id)
    if not lesson:
        return False
    
    # Delete attempts first (cascade should handle this, but being explicit)
    db.execute("DELETE FROM lesson_attempts WHERE lesson_id = ?", (lesson_id,))
    
    # Delete lesson
    db.execute("DELETE FROM lessons WHERE id = ? AND user_id = ?", (lesson_id, user_id))
    
    return True


def init_db(db_path: str = None) -> DB:
    """Initialize database schema and return DB instance."""
    if db_path is None:
        db_path = os.environ.get("SEED_DB_PATH", "./seed.db")
    
    db = DB(db_path)
    db.init_schema()
    return db
