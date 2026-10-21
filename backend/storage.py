"""
SQLite asynchronous storage layer for Fadfada Psychiatric Agent.
Enforces WAL mode, foreign keys, and structured table definitions for
sessions, transcripts, Law 151/2020 consents, and longitudinal patient memories.
"""

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("fadfada.storage")


class SimpleStorage:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            self.db_path = base_dir / "fadfada.db"
        else:
            self.db_path = Path(db_path)

        # Ensure parent directory exists (especially for /tmp on serverless)
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        self._lock = asyncio.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
        except Exception:
            try:
                conn.execute("PRAGMA journal_mode = DELETE;")
            except Exception:
                pass
        try:
            conn.execute("PRAGMA synchronous = NORMAL;")
        except Exception:
            pass
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
        except Exception:
            pass
        return conn

    def _init_db(self) -> None:
        """Synchronously initialize schema if not already present."""
        with self._get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                voice TEXT NOT NULL DEFAULT 'Aoede',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                ended_at TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS patient_consent (
                patient_id TEXT NOT NULL,
                consent_type TEXT NOT NULL,
                granted INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (patient_id, consent_type)
            );

            CREATE TABLE IF NOT EXISTS patient_memories (
                id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                category TEXT NOT NULL,
                fact_ar TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                status TEXT NOT NULL DEFAULT 'approved',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)

    async def create_session(self, session_id: str, patient_id: str, voice: str = "Aoede") -> Dict[str, Any]:
        async with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            loop = asyncio.get_running_loop()

            def _query():
                with self._get_connection() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO sessions (id, patient_id, voice, status, created_at) VALUES (?, ?, ?, 'active', ?)",
                        (session_id, patient_id, voice, now),
                    )
                return {"id": session_id, "patient_id": patient_id, "voice": voice, "status": "active", "created_at": now}

            return await loop.run_in_executor(None, _query)

    async def end_session(self, session_id: str) -> None:
        async with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            loop = asyncio.get_running_loop()

            def _query():
                with self._get_connection() as conn:
                    conn.execute("UPDATE sessions SET status = 'completed', ended_at = ? WHERE id = ?", (now, session_id))

            await loop.run_in_executor(None, _query)

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_running_loop()

        def _query():
            with self._get_connection() as conn:
                cur = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
                row = cur.fetchone()
                return dict(row) if row else None

        return await loop.run_in_executor(None, _query)

    async def add_message(self, session_id: str, role: str, text: str) -> None:
        async with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            loop = asyncio.get_running_loop()

            def _query():
                with self._get_connection() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO sessions (id, patient_id, voice, status, created_at) VALUES (?, 'default_user', 'Aoede', 'active', ?)",
                        (session_id, now),
                    )
                    conn.execute(
                        "INSERT INTO messages (session_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                        (session_id, role, text, now),
                    )

            await loop.run_in_executor(None, _query)

    async def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        loop = asyncio.get_running_loop()

        def _query():
            with self._get_connection() as conn:
                cur = conn.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
                return [dict(row) for row in cur.fetchall()]

        return await loop.run_in_executor(None, _query)

    async def set_consent(self, patient_id: str, consent_type: str, granted: bool) -> None:
        async with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            val = 1 if granted else 0
            loop = asyncio.get_running_loop()

            def _query():
                with self._get_connection() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO patient_consent (patient_id, consent_type, granted, updated_at) VALUES (?, ?, ?, ?)",
                        (patient_id, consent_type, val, now),
                    )

            await loop.run_in_executor(None, _query)

    async def get_consent(self, patient_id: str, consent_type: str) -> bool:
        loop = asyncio.get_running_loop()

        def _query():
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT granted FROM patient_consent WHERE patient_id = ? AND consent_type = ?",
                    (patient_id, consent_type),
                )
                row = cur.fetchone()
                return bool(row["granted"]) if row else False

        return await loop.run_in_executor(None, _query)

    async def save_memory(
        self,
        memory_id: str,
        patient_id: str,
        category: str,
        fact_ar: str,
        confidence: float = 1.0,
        status: str = "approved",
    ) -> Dict[str, Any]:
        async with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            loop = asyncio.get_running_loop()

            def _query():
                with self._get_connection() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO patient_memories
                        (id, patient_id, category, fact_ar, confidence, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (memory_id, patient_id, category, fact_ar, confidence, status, now, now),
                    )
                return {
                    "id": memory_id,
                    "patient_id": patient_id,
                    "category": category,
                    "fact_ar": fact_ar,
                    "confidence": confidence,
                    "status": status,
                    "created_at": now,
                    "updated_at": now,
                }

            return await loop.run_in_executor(None, _query)

    async def get_memories(self, patient_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        loop = asyncio.get_running_loop()

        def _query():
            with self._get_connection() as conn:
                if status:
                    cur = conn.execute(
                        "SELECT * FROM patient_memories WHERE patient_id = ? AND status = ? ORDER BY created_at DESC",
                        (patient_id, status),
                    )
                else:
                    cur = conn.execute(
                        "SELECT * FROM patient_memories WHERE patient_id = ? ORDER BY created_at DESC",
                        (patient_id,),
                    )
                return [dict(row) for row in cur.fetchall()]

        return await loop.run_in_executor(None, _query)

    async def delete_memory(self, memory_id: str, patient_id: str) -> bool:
        """Right to Erasure under Egyptian Law 151/2020."""
        async with self._lock:
            loop = asyncio.get_running_loop()

            def _query():
                with self._get_connection() as conn:
                    cur = conn.execute("DELETE FROM patient_memories WHERE id = ? AND patient_id = ?", (memory_id, patient_id))
                    return cur.rowcount > 0

            return await loop.run_in_executor(None, _query)
