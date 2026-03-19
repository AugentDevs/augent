"""
Augent Memory - Transcription memory and model caching system

Provides persistent memory for transcriptions to avoid re-processing
the same audio files, and in-memory model caching to avoid reloading.
"""

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MemorizedTranscription:
    """Stored transcription data."""

    audio_hash: str
    model_size: str
    language: str
    duration: float
    text: str
    words: list
    segments: list
    created_at: float
    file_path: str  # Original file path (for reference)
    title: str = ""  # Derived from filename, for UX display
    source_url: str = ""  # Original URL (YouTube, etc.) if downloaded


class TranscriptionMemory:
    """
    SQLite-based memory for audio transcriptions.

    Stores transcriptions keyed by audio file hash + model size,
    so the same file transcribed with different models is stored separately.
    """

    def __init__(self, memory_dir: Optional[str] = None):
        if memory_dir is None:
            memory_dir = os.path.expanduser("~/.augent/memory")

        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.memory_dir / "transcriptions.db"
        self.md_dir = self.memory_dir / "transcriptions"
        self.md_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcriptions (
                    cache_key TEXT PRIMARY KEY,
                    audio_hash TEXT NOT NULL,
                    model_size TEXT NOT NULL,
                    language TEXT,
                    duration REAL,
                    text TEXT,
                    words TEXT,
                    segments TEXT,
                    created_at REAL,
                    file_path TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audio_hash
                ON transcriptions(audio_hash)
            """)

            # Migration: add columns for existing DBs
            for column, col_type in [
                ("title", "TEXT"),
                ("md_path", "TEXT"),
                ("source_url", "TEXT"),
                ("translated_text", "TEXT"),
                ("translated_segments", "TEXT"),
                ("translated_md_path", "TEXT"),
            ]:
                try:
                    conn.execute(
                        f"ALTER TABLE transcriptions ADD COLUMN {column} {col_type} DEFAULT ''"
                    )
                except sqlite3.OperationalError:
                    pass  # Column already exists

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_title
                ON transcriptions(title)
            """)

            # Embeddings cache table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    cache_key TEXT PRIMARY KEY,
                    audio_hash TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    segment_count INTEGER,
                    embedding_dim INTEGER,
                    embeddings BLOB,
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_embeddings_hash
                ON embeddings(audio_hash)
            """)

            # Source URL table — maps audio_hash to source URL (persists across sessions)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS source_urls (
                    audio_hash TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    created_at REAL
                )
            """)

            # Speaker diarization cache table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS diarization (
                    cache_key TEXT PRIMARY KEY,
                    audio_hash TEXT NOT NULL,
                    num_speakers INTEGER,
                    speakers TEXT,
                    turns TEXT,
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_diarization_hash
                ON diarization(audio_hash)
            """)

            # Tags table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    category TEXT DEFAULT '',
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name)
            """)

            # Junction table: transcriptions <-> tags (many-to-many)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcription_tags (
                    cache_key TEXT NOT NULL,
                    tag_id INTEGER NOT NULL,
                    source TEXT DEFAULT 'auto',
                    created_at REAL,
                    PRIMARY KEY (cache_key, tag_id),
                    FOREIGN KEY (cache_key) REFERENCES transcriptions(cache_key),
                    FOREIGN KEY (tag_id) REFERENCES tags(tag_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tt_cache_key
                ON transcription_tags(cache_key)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tt_tag_id
                ON transcription_tags(tag_id)
            """)

            conn.commit()

    @staticmethod
    def _validate_path(file_path: str) -> Path:
        """Resolve and validate that a path is under ~ or /tmp. Returns a safe Path."""
        resolved = Path(file_path).resolve()
        home = Path.home().resolve()
        tmp = Path("/tmp").resolve()
        if resolved.is_relative_to(home) or resolved.is_relative_to(tmp):
            return resolved
        raise ValueError(
            f"Access denied: path must be under home directory or /tmp: {resolved}"
        )

    @staticmethod
    def hash_audio_file(file_path: str) -> str:
        """
        Generate a hash of the audio file content.
        Uses SHA256 for reliable uniqueness.
        """
        hasher = hashlib.sha256()
        safe = TranscriptionMemory._validate_path(file_path)
        if not safe.is_file():
            raise FileNotFoundError(f"Audio file not found: {safe}")
        with safe.open("rb") as f:
            # Read in chunks for memory efficiency with large files
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _cache_key(audio_hash: str, model_size: str) -> str:
        """Generate cache key from audio hash and model size."""
        return f"{audio_hash}:{model_size}"

    @staticmethod
    def _title_from_path(file_path: str) -> str:
        """Derive a human-readable title from an audio file path."""
        basename = os.path.basename(file_path)
        title, _ = os.path.splitext(basename)
        return title

    @staticmethod
    def _sanitize_filename(title: str) -> str:
        """Sanitize a title for use as a filename."""
        sanitized = "".join(
            c if c.isalnum() or c in "-_ " else "_" for c in title
        ).strip()
        sanitized = re.sub(r"[_\s]+", "_", sanitized)
        return sanitized[:200] if sanitized else "untitled"

    def _write_markdown(
        self,
        title: str,
        transcription: Dict[str, Any],
        file_path: str,
        source_url: str = "",
    ) -> Optional[Path]:
        """Write a markdown transcription file. Returns the path or None on error."""
        try:
            sanitized = self._sanitize_filename(title)
            md_path = self.md_dir / f"{sanitized}.md"

            duration = transcription.get("duration", 0)
            mins = int(duration // 60)
            secs = int(duration % 60)

            lines = [
                f"# {title}",
                "",
                f"**Source:** `{os.path.basename(file_path)}`  ",
                f"**Duration:** {mins}:{secs:02d}  ",
                f"**Language:** {transcription.get('language', 'unknown')}  ",
            ]
            if source_url:
                lines.append(f"**URL:** {source_url}  ")
            lines.extend(
                [
                    "",
                    "---",
                    "",
                    "## Transcription",
                    "",
                ]
            )

            segments = transcription.get("segments", [])
            for seg in segments:
                start = seg.get("start", 0)
                m = int(start // 60)
                s = int(start % 60)
                text = seg.get("text", "").strip()
                lines.append(f"**[{m}:{s:02d}]** {text}")
                lines.append("")

            if not segments:
                lines.append(transcription.get("text", ""))
                lines.append("")

            md_path.write_text("\n".join(lines), encoding="utf-8")
            return md_path
        except Exception:
            return None

    def get(self, file_path: str, model_size: str) -> Optional[MemorizedTranscription]:
        """
        Retrieve stored transcription if available.

        Args:
            file_path: Path to audio file
            model_size: Whisper model size used

        Returns:
            MemorizedTranscription if found, None otherwise
        """
        try:
            audio_hash = self.hash_audio_file(file_path)
            cache_key = self._cache_key(audio_hash, model_size)

            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        "SELECT * FROM transcriptions WHERE cache_key = ?", (cache_key,)
                    )
                    row = cursor.fetchone()

                    if row is None:
                        return None

                    return MemorizedTranscription(
                        audio_hash=row["audio_hash"],
                        model_size=row["model_size"],
                        language=row["language"],
                        duration=row["duration"],
                        text=row["text"],
                        words=json.loads(row["words"]),
                        segments=json.loads(row["segments"]),
                        created_at=row["created_at"],
                        file_path=row["file_path"],
                        title=row["title"] if "title" in row.keys() else "",
                        source_url=(
                            row["source_url"] if "source_url" in row.keys() else ""
                        ),
                    )
        except Exception:
            # Cache miss on any error
            return None

    def set(
        self,
        file_path: str,
        model_size: str,
        transcription: Dict[str, Any],
        source_url: str = "",
    ) -> None:
        """
        Store transcription in memory.

        Args:
            file_path: Path to audio file
            model_size: Whisper model size used
            transcription: Transcription result dict with text, words, segments, etc.
        """
        try:
            audio_hash = self.hash_audio_file(file_path)
            cache_key = self._cache_key(audio_hash, model_size)
            title = self._title_from_path(file_path)

            # Write markdown file
            md_path = self._write_markdown(title, transcription, file_path, source_url)

            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO transcriptions
                        (cache_key, audio_hash, model_size, language, duration,
                         text, words, segments, created_at, file_path, title, md_path,
                         source_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            cache_key,
                            audio_hash,
                            model_size,
                            transcription.get("language", "unknown"),
                            transcription.get("duration", 0),
                            transcription.get("text", ""),
                            json.dumps(transcription.get("words", [])),
                            json.dumps(transcription.get("segments", [])),
                            time.time(),
                            file_path,
                            title,
                            str(md_path) if md_path else "",
                            source_url,
                        ),
                    )
                    conn.commit()
        except Exception:
            # Silently fail on memory write errors
            pass

    def store_translation(
        self,
        file_path: str,
        model_size: str,
        translated_text: str,
    ) -> Optional[str]:
        """
        Store a translated version of an existing transcription.

        Writes the English text into translated_text/translated_segments columns
        and creates a sibling .md file with (eng) suffix.

        Args:
            file_path: Path to the original audio file (must already be transcribed)
            model_size: Whisper model size used for the original transcription
            translated_text: The full English translation text

        Returns:
            Path to the translated .md file, or None on error
        """
        try:
            audio_hash = self.hash_audio_file(file_path)
            cache_key = self._cache_key(audio_hash, model_size)

            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute(
                        "SELECT title, segments, duration, file_path, source_url "
                        "FROM transcriptions WHERE cache_key = ?",
                        (cache_key,),
                    ).fetchone()
                    if not row:
                        return None

                    title = row["title"] or self._title_from_path(file_path)
                    duration = row["duration"] or 0
                    source_url = row["source_url"] or ""

                    # Write clean English translation markdown — no timestamps,
                    # no segment mapping. This is a translation, not a re-transcription.
                    eng_title = f"{title} (eng)"
                    sanitized = self._sanitize_filename(eng_title)
                    translated_md_path = self.md_dir / f"{sanitized}.md"

                    mins = int(duration // 60)
                    secs = int(duration % 60)
                    src_basename = os.path.basename(row["file_path"] or file_path)

                    lines = [
                        f"# {eng_title}",
                        "",
                        f"**Source:** `{src_basename}`  ",
                        f"**Duration:** {mins}:{secs:02d}  ",
                        "**Language:** en (translated)  ",
                    ]
                    if source_url:
                        lines.append(f"**URL:** {source_url}  ")
                    lines.extend(
                        ["", "---", "", "## Translation", "", translated_text, ""]
                    )
                    translated_md_path.write_text("\n".join(lines), encoding="utf-8")

                    conn.execute(
                        """UPDATE transcriptions
                           SET translated_text = ?,
                               translated_segments = ?,
                               translated_md_path = ?
                           WHERE cache_key = ?""",
                        (
                            translated_text,
                            "[]",
                            str(translated_md_path) if translated_md_path else "",
                            cache_key,
                        ),
                    )
                    conn.commit()

                    return str(translated_md_path) if translated_md_path else None
        except Exception:
            return None

    def update_source_url(
        self, file_path: str, model_size: str, source_url: str
    ) -> None:
        """Attach a source URL to an existing transcription entry."""
        try:
            audio_hash = self.hash_audio_file(file_path)
            cache_key = self._cache_key(audio_hash, model_size)
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        "UPDATE transcriptions SET source_url = ? WHERE cache_key = ?",
                        (source_url, cache_key),
                    )
                    conn.commit()
        except Exception:
            pass

    def get_source_url(self, file_path: str, model_size: str) -> str:
        """Get the source URL for a transcription, if any."""
        try:
            audio_hash = self.hash_audio_file(file_path)
            cache_key = self._cache_key(audio_hash, model_size)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT source_url FROM transcriptions WHERE cache_key = ?",
                    (cache_key,),
                )
                row = cursor.fetchone()
                return row[0] if row and row[0] else ""
        except Exception:
            return ""

    def save_source_url(self, file_path: str, source_url: str) -> None:
        """Persist a source URL for an audio file (by hash). Survives restarts."""
        if not source_url:
            return
        try:
            audio_hash = self.hash_audio_file(file_path)
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO source_urls
                           (audio_hash, source_url, created_at)
                           VALUES (?, ?, ?)""",
                        (audio_hash, source_url, time.time()),
                    )
                    conn.commit()
                    # Also backfill any existing transcriptions of this file
                    conn.execute(
                        """UPDATE transcriptions SET source_url = ?
                           WHERE audio_hash = ? AND (source_url IS NULL OR source_url = '')""",
                        (source_url, audio_hash),
                    )
                    conn.commit()
        except Exception:
            pass

    def get_by_source_url(
        self, source_url: str, model_size: str
    ) -> Optional["MemorizedTranscription"]:
        """Look up a transcription by its source URL and model size."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM transcriptions WHERE source_url = ? AND model_size = ?",
                    (source_url, model_size),
                )
                row = cursor.fetchone()
                if row:
                    return MemorizedTranscription(
                        audio_hash=row["audio_hash"],
                        model_size=row["model_size"],
                        language=row["language"],
                        duration=row["duration"],
                        text=row["text"],
                        words=json.loads(row["words"]) if row["words"] else [],
                        segments=json.loads(row["segments"]) if row["segments"] else [],
                        created_at=row["created_at"],
                        file_path=row["file_path"] or "",
                        title=row["title"] or "",
                        source_url=row["source_url"] or "",
                    )
        except Exception:
            pass
        return None

    def get_source_url_by_hash(self, file_path: str) -> str:
        """Look up a persisted source URL by audio file hash. No model_size needed."""
        try:
            audio_hash = self.hash_audio_file(file_path)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT source_url FROM source_urls WHERE audio_hash = ?",
                    (audio_hash,),
                )
                row = cursor.fetchone()
                return row[0] if row and row[0] else ""
        except Exception:
            return ""

    def clear(self) -> int:
        """
        Clear all stored transcriptions and markdown files.

        Returns:
            Number of entries cleared
        """
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM transcriptions")
                count = cursor.fetchone()[0]

                # Collect md_path values before deleting rows
                md_cursor = conn.execute(
                    "SELECT md_path FROM transcriptions WHERE md_path IS NOT NULL AND md_path != ''"
                )
                md_paths = [row[0] for row in md_cursor.fetchall()]

                conn.execute("DELETE FROM transcriptions")
                conn.execute("DELETE FROM embeddings")
                conn.execute("DELETE FROM diarization")
                conn.execute("DELETE FROM source_urls")
                conn.execute("DELETE FROM transcription_tags")
                conn.execute("DELETE FROM tags")
                conn.commit()

            # Delete markdown files outside the DB transaction
            for md_path in md_paths:
                try:
                    if os.path.exists(md_path):
                        os.remove(md_path)
                except OSError:
                    pass

            return count

    def stats(self) -> Dict[str, Any]:
        """Get memory statistics including title listing."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM transcriptions")
            count = cursor.fetchone()[0]

            cursor = conn.execute("SELECT SUM(duration) FROM transcriptions")
            total_duration = cursor.fetchone()[0] or 0

            # Get titles
            cursor = conn.execute(
                "SELECT title, model_size, duration FROM transcriptions ORDER BY created_at DESC"
            )
            titles = []
            for row in cursor.fetchall():
                titles.append(
                    {
                        "title": row[0] or "(untitled)",
                        "model": row[1],
                        "duration": row[2] or 0,
                    }
                )

            # Get DB file size
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

            # Get md dir size
            md_size = (
                sum(f.stat().st_size for f in self.md_dir.glob("*.md"))
                if self.md_dir.exists()
                else 0
            )

            cursor = conn.execute("SELECT COUNT(*) FROM embeddings")
            embedding_count = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM diarization")
            diarization_count = cursor.fetchone()[0]

            try:
                cursor = conn.execute("SELECT COUNT(*) FROM tags")
                tag_count = cursor.fetchone()[0]
            except Exception:
                tag_count = 0

            return {
                "entries": count,
                "embedding_entries": embedding_count,
                "diarization_entries": diarization_count,
                "tag_count": tag_count,
                "total_audio_duration_hours": round(total_duration / 3600, 2),
                "memory_size_mb": round((db_size + md_size) / (1024 * 1024), 2),
                "memory_path": str(self.db_path),
                "md_dir": str(self.md_dir),
                "titles": titles,
            }

    def get_by_title(self, title: str) -> List[MemorizedTranscription]:
        """
        Look up stored transcriptions by title (substring match, case-insensitive).

        Args:
            title: Title to search for (supports partial match)

        Returns:
            List of MemorizedTranscription objects matching the title
        """
        results = []
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        "SELECT * FROM transcriptions WHERE title LIKE ?",
                        (f"%{title}%",),
                    )
                    for row in cursor.fetchall():
                        results.append(
                            MemorizedTranscription(
                                audio_hash=row["audio_hash"],
                                model_size=row["model_size"],
                                language=row["language"],
                                duration=row["duration"],
                                text=row["text"],
                                words=json.loads(row["words"]),
                                segments=json.loads(row["segments"]),
                                created_at=row["created_at"],
                                file_path=row["file_path"],
                                title=row["title"] if "title" in row.keys() else "",
                                source_url=(
                                    row["source_url"]
                                    if "source_url" in row.keys()
                                    else ""
                                ),
                            )
                        )
        except Exception:
            pass
        return results

    def list_all(self) -> List[Dict[str, Any]]:
        """
        List all stored transcriptions with metadata.

        Returns:
            List of dicts with title, duration, date, model_size, md_path, file_path
        """
        entries = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT cache_key, title, duration, created_at, model_size, "
                    "md_path, file_path, source_url, language "
                    "FROM transcriptions ORDER BY created_at DESC"
                )
                for row in cursor.fetchall():
                    created = row["created_at"]
                    date_str = (
                        datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M")
                        if created
                        else ""
                    )

                    duration = row["duration"] or 0
                    h = int(duration // 3600)
                    m = int((duration % 3600) // 60)
                    s = int(duration % 60)
                    dur_fmt = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"

                    entries.append(
                        {
                            "cache_key": row["cache_key"],
                            "title": row["title"]
                            or os.path.basename(row["file_path"] or ""),
                            "duration": duration,
                            "duration_formatted": dur_fmt,
                            "date": date_str,
                            "model_size": row["model_size"],
                            "md_path": row["md_path"] or "",
                            "file_path": row["file_path"] or "",
                            "source_url": row["source_url"] or "",
                            "language": row["language"] or "",
                        }
                    )
        except Exception:
            pass
        return entries

    def get_by_cache_key(self, cache_key: str) -> Optional[MemorizedTranscription]:
        """Retrieve a transcription by its cache_key (audio_hash:model_size)."""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        "SELECT * FROM transcriptions WHERE cache_key = ?",
                        (cache_key,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    return MemorizedTranscription(
                        audio_hash=row["audio_hash"],
                        model_size=row["model_size"],
                        language=row["language"],
                        duration=row["duration"],
                        text=row["text"],
                        words=json.loads(row["words"]),
                        segments=json.loads(row["segments"]),
                        created_at=row["created_at"],
                        file_path=row["file_path"],
                        title=row["title"] if "title" in row.keys() else "",
                        source_url=(
                            row["source_url"] if "source_url" in row.keys() else ""
                        ),
                    )
        except Exception:
            return None

    def delete_by_cache_key(self, cache_key: str) -> bool:
        """Delete a single transcription by cache_key. Returns True if deleted."""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    # Get md_path before deleting
                    cursor = conn.execute(
                        "SELECT md_path FROM transcriptions WHERE cache_key = ?",
                        (cache_key,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return False

                    md_path = row[0] if row[0] else ""

                    conn.execute(
                        "DELETE FROM transcriptions WHERE cache_key = ?",
                        (cache_key,),
                    )
                    conn.execute(
                        "DELETE FROM embeddings WHERE cache_key = ?",
                        (cache_key,),
                    )
                    conn.execute(
                        "DELETE FROM transcription_tags WHERE cache_key = ?",
                        (cache_key,),
                    )
                    conn.commit()

                # Delete markdown file outside transaction
                if md_path:
                    try:
                        if os.path.exists(md_path):
                            os.remove(md_path)
                    except OSError:
                        pass

                return True
        except Exception:
            return False

    # --- Embeddings memory methods ---

    @staticmethod
    def _embeddings_cache_key(audio_hash: str, embedding_model: str) -> str:
        return f"{audio_hash}:{embedding_model}"

    def get_embeddings(
        self, audio_hash: str, embedding_model: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieve stored embeddings. Returns dict with numpy array or None."""
        import numpy as np

        cache_key = self._embeddings_cache_key(audio_hash, embedding_model)
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        "SELECT * FROM embeddings WHERE cache_key = ?", (cache_key,)
                    )
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    return {
                        "embeddings": np.frombuffer(
                            row["embeddings"], dtype=np.float32
                        ).reshape(row["segment_count"], row["embedding_dim"]),
                        "segment_count": row["segment_count"],
                        "embedding_dim": row["embedding_dim"],
                    }
        except Exception:
            return None

    def set_embeddings(
        self,
        audio_hash: str,
        embedding_model: str,
        embeddings,
        segment_count: int,
        embedding_dim: int,
    ) -> None:
        """Store embeddings in memory. embeddings should be a numpy ndarray."""
        cache_key = self._embeddings_cache_key(audio_hash, embedding_model)
        blob = embeddings.astype("float32").tobytes()
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO embeddings
                        (cache_key, audio_hash, embedding_model, segment_count,
                         embedding_dim, embeddings, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            cache_key,
                            audio_hash,
                            embedding_model,
                            segment_count,
                            embedding_dim,
                            blob,
                            time.time(),
                        ),
                    )
                    conn.commit()
        except Exception:
            pass

    def get_all_with_segments(self) -> List[Dict[str, Any]]:
        """
        Retrieve all transcriptions with parsed segments (no embeddings).

        GROUP BY audio_hash deduplicates when same audio was transcribed
        with multiple Whisper model sizes.

        Returns:
            List of dicts with audio_hash, title, file_path, duration,
            segments (parsed JSON).
        """
        results = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT audio_hash, title, file_path, duration, segments,
                           source_url
                    FROM transcriptions
                    GROUP BY audio_hash
                """)

                for row in cursor.fetchall():
                    results.append(
                        {
                            "audio_hash": row["audio_hash"],
                            "title": row["title"] or "",
                            "file_path": row["file_path"] or "",
                            "duration": row["duration"] or 0,
                            "segments": (
                                json.loads(row["segments"]) if row["segments"] else []
                            ),
                            "source_url": row["source_url"] or "",
                        }
                    )
        except Exception:
            pass
        return results

    def get_all_with_embeddings(
        self, embedding_model: str = "all-MiniLM-L6-v2"
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all transcriptions with their embeddings (if available).

        LEFT JOINs transcriptions with embeddings so files without embeddings
        are still returned (with embeddings=None). GROUP BY audio_hash
        deduplicates when same audio was transcribed with multiple model sizes.

        Returns:
            List of dicts with audio_hash, title, file_path, duration,
            segments (parsed JSON), embeddings (numpy or None),
            segment_count, embedding_dim.
        """
        import numpy as np

        results = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """
                    SELECT t.audio_hash, t.title, t.file_path, t.duration, t.segments,
                           t.source_url,
                           e.embeddings AS emb_blob, e.segment_count, e.embedding_dim
                    FROM transcriptions t
                    LEFT JOIN embeddings e
                        ON t.audio_hash = e.audio_hash
                        AND e.embedding_model = ?
                    GROUP BY t.audio_hash
                """,
                    (embedding_model,),
                )

                for row in cursor.fetchall():
                    emb = None
                    seg_count = row["segment_count"]
                    emb_dim = row["embedding_dim"]
                    if row["emb_blob"] is not None and seg_count and emb_dim:
                        emb = np.frombuffer(row["emb_blob"], dtype=np.float32).reshape(
                            seg_count, emb_dim
                        )

                    results.append(
                        {
                            "audio_hash": row["audio_hash"],
                            "title": row["title"] or "",
                            "file_path": row["file_path"] or "",
                            "duration": row["duration"] or 0,
                            "segments": (
                                json.loads(row["segments"]) if row["segments"] else []
                            ),
                            "source_url": row["source_url"] or "",
                            "embeddings": emb,
                            "segment_count": seg_count or 0,
                            "embedding_dim": emb_dim or 0,
                        }
                    )
        except Exception:
            pass
        return results

    # --- Diarization memory methods ---

    @staticmethod
    def _diarization_cache_key(audio_hash: str, num_speakers) -> str:
        return f"{audio_hash}:spk:{num_speakers}"

    def get_diarization(
        self, audio_hash: str, num_speakers=None
    ) -> Optional[Dict[str, Any]]:
        """Retrieve stored diarization result."""
        cache_key = self._diarization_cache_key(audio_hash, num_speakers)
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        "SELECT * FROM diarization WHERE cache_key = ?", (cache_key,)
                    )
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    return {
                        "speakers": json.loads(row["speakers"]),
                        "turns": json.loads(row["turns"]),
                    }
        except Exception:
            return None

    def set_diarization(
        self, audio_hash: str, speakers: list, turns: list, num_speakers=None
    ) -> None:
        """Store diarization result in memory."""
        cache_key = self._diarization_cache_key(audio_hash, num_speakers)
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO diarization
                        (cache_key, audio_hash, num_speakers, speakers, turns, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """,
                        (
                            cache_key,
                            audio_hash,
                            num_speakers,
                            json.dumps(speakers),
                            json.dumps(turns),
                            time.time(),
                        ),
                    )
                    conn.commit()
        except Exception:
            pass

    # ── Tag methods ──────────────────────────────────────────────────

    def add_tags(
        self,
        cache_key: str,
        tags: List[str],
        category: str = "manual",
        source: str = "manual",
    ) -> List[dict]:
        """Add tags to a transcription. Creates tags if they don't exist."""
        import time

        now = time.time()
        added = []
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                for tag_name in tags:
                    tag_name = tag_name.strip()
                    if not tag_name:
                        continue
                    # Upsert tag
                    conn.execute(
                        "INSERT OR IGNORE INTO tags (name, category, created_at) VALUES (?, ?, ?)",
                        (tag_name, category, now),
                    )
                    # Get tag_id
                    cursor = conn.execute(
                        "SELECT tag_id FROM tags WHERE name = ?", (tag_name,)
                    )
                    tag_id = cursor.fetchone()[0]
                    # Link to transcription
                    conn.execute(
                        "INSERT OR IGNORE INTO transcription_tags (cache_key, tag_id, source, created_at) VALUES (?, ?, ?, ?)",
                        (cache_key, tag_id, source, now),
                    )
                    added.append(
                        {"name": tag_name, "category": category, "source": source}
                    )
                conn.commit()
        return added

    def remove_tags(self, cache_key: str, tags: List[str]) -> int:
        """Remove tags from a transcription. Returns number removed."""
        removed = 0
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                for tag_name in tags:
                    tag_name = tag_name.strip()
                    if not tag_name:
                        continue
                    cursor = conn.execute(
                        "SELECT tag_id FROM tags WHERE name = ?", (tag_name,)
                    )
                    row = cursor.fetchone()
                    if row:
                        conn.execute(
                            "DELETE FROM transcription_tags WHERE cache_key = ? AND tag_id = ?",
                            (cache_key, row[0]),
                        )
                        removed += conn.total_changes
                conn.commit()
        return removed

    def get_tags(self, cache_key: str) -> List[dict]:
        """Get all tags for a transcription."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT t.name, t.category, tt.source
                FROM transcription_tags tt
                JOIN tags t ON tt.tag_id = t.tag_id
                WHERE tt.cache_key = ?
                ORDER BY t.name
                """,
                (cache_key,),
            )
            return [
                {"name": row[0], "category": row[1], "source": row[2]}
                for row in cursor.fetchall()
            ]

    def filter_by_tag(self, tag_name: str) -> List[dict]:
        """Find all transcriptions with a given tag."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT tr.cache_key, tr.title, tr.duration, tr.model_size,
                       tr.file_path, tr.language, tr.created_at
                FROM transcription_tags tt
                JOIN tags t ON tt.tag_id = t.tag_id
                JOIN transcriptions tr ON tt.cache_key = tr.cache_key
                WHERE t.name = ? COLLATE NOCASE
                ORDER BY tr.created_at DESC
                """,
                (tag_name,),
            )
            results = []
            for row in cursor.fetchall():
                duration = row[2] or 0
                m, s = divmod(int(duration), 60)
                h, m = divmod(m, 60)
                fmt = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
                results.append(
                    {
                        "cache_key": row[0],
                        "title": row[1] or "(untitled)",
                        "duration": duration,
                        "duration_formatted": fmt,
                        "model_size": row[3],
                        "file_path": row[4],
                        "language": row[5],
                    }
                )
            return results

    _STOPWORDS = frozenset(
        "the a an and or but in on at to for of is it this that was were be been "
        "being have has had do does did will would shall should may might can could "
        "with from by as are am not no nor so if then than too very just about above "
        "after again all also any because before between both each few more most other "
        "some such only own same these those through under until while into over during "
        "out up down off here there when where which who whom what how its his her he "
        "she they them their we our you your my me us him i one two three four five "
        "six seven eight nine ten much many well back even still way take come go get "
        "got make like know think say see look find give tell use call work try ask "
        "need feel become leave put mean keep let begin seem help show hear play run "
        "move live believe hold bring happen write provide sit stand lose pay meet "
        "include continue set learn change lead understand watch follow stop create "
        "speak read allow add spend grow open walk win offer remember love consider "
        "appear buy wait serve die send expect build stay fall cut reach kill remain "
        "right really actually going something people thing things yeah okay sure "
        "oh um uh like kind sort just gonna want know mean literally basically "
        "pretty much stuff lot already said".split()
    )

    def auto_tag(self, cache_key: str, text: str) -> List[dict]:
        """Extract entities from transcription text and auto-tag."""
        import re

        if not text or len(text) < 50:
            return []

        words = text.split()
        word_count = len(words)
        if word_count < 20:
            return []

        # Strategy 1: Capitalized multi-word phrases (likely proper nouns)
        cap_phrases = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text)
        phrase_freq = {}
        for p in cap_phrases:
            p_lower = p.lower()
            if p_lower not in self._STOPWORDS:
                phrase_freq[p] = phrase_freq.get(p, 0) + 1

        # Strategy 2: Repeated capitalized single words (not at sentence start)
        # Look for capitalized words NOT after . ! ? or start of text
        single_caps = re.findall(r"(?<![.!?\n])\s([A-Z][a-z]{2,})\b", text)
        single_freq = {}
        for w in single_caps:
            w_lower = w.lower()
            if w_lower not in self._STOPWORDS and len(w) > 2:
                single_freq[w] = single_freq.get(w, 0) + 1

        # Strategy 3: Frequency-based keywords (for all-lowercase whisper output)
        all_lowercase = text == text.lower()
        freq_tags = {}
        if all_lowercase:
            for w in words:
                w_clean = re.sub(r"[^a-z]", "", w.lower())
                if len(w_clean) > 3 and w_clean not in self._STOPWORDS:
                    freq_tags[w_clean] = freq_tags.get(w_clean, 0) + 1

        # Collect tags with thresholds
        extracted = []
        company_suffixes = {
            "inc",
            "corp",
            "llc",
            "ltd",
            "co",
            "group",
            "foundation",
            "labs",
            "ai",
        }

        # Multi-word phrases (threshold: 2+)
        for phrase, count in phrase_freq.items():
            if count >= 2:
                last_word = phrase.split()[-1].lower()
                cat = "company" if last_word in company_suffixes else "person"
                extracted.append({"name": phrase, "category": cat, "count": count})

        # Single capitalized words (threshold: 3+)
        for word, count in single_freq.items():
            if count >= 3:
                extracted.append({"name": word, "category": "topic", "count": count})

        # Frequency keywords for all-lowercase text (threshold: relative to length)
        if all_lowercase:
            threshold = max(3, word_count // 200)
            for word, count in freq_tags.items():
                if count >= threshold:
                    extracted.append(
                        {"name": word, "category": "topic", "count": count}
                    )

        # Deduplicate (case-insensitive)
        seen = set()
        unique = []
        for tag in sorted(extracted, key=lambda x: x["count"], reverse=True):
            key = tag["name"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(tag)

        # Limit to top 15
        unique = unique[:15]

        if unique:
            categories = {t["name"]: t["category"] for t in unique}
            for tag in unique:
                self.add_tags(
                    cache_key,
                    [tag["name"]],
                    category=categories[tag["name"]],
                    source="auto",
                )

        return unique


class ModelCache:
    """
    In-memory cache for loaded Whisper models.

    Keeps models loaded to avoid expensive reload times
    on consecutive transcriptions.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._models = {}
                    cls._instance._model_lock = threading.Lock()
        return cls._instance

    def get(self, model_size: str, device: str = "auto", compute_type: str = "auto"):
        """
        Get a cached model or load a new one.

        Args:
            model_size: Whisper model size (tiny, base, small, medium, large)
            device: Device to use (auto, cpu, cuda)
            compute_type: Compute type (auto, float16, int8, etc.)

        Returns:
            Loaded WhisperModel instance
        """
        cache_key = f"{model_size}:{device}:{compute_type}"

        with self._model_lock:
            if cache_key not in self._models:
                from faster_whisper import WhisperModel

                # Determine compute type based on device if auto
                if compute_type == "auto":
                    import torch

                    if torch.cuda.is_available():
                        compute_type = "float16"
                    else:
                        compute_type = "int8"

                self._models[cache_key] = WhisperModel(
                    model_size, device=device, compute_type=compute_type
                )

            return self._models[cache_key]

    def clear(self):
        """Clear all cached models to free memory."""
        with self._model_lock:
            self._models.clear()

    def loaded_models(self) -> list:
        """List currently loaded model sizes."""
        return list(self._models.keys())


# Global instances for easy access
_transcription_memory: Optional[TranscriptionMemory] = None
_model_cache: Optional[ModelCache] = None


def get_transcription_memory(memory_dir: Optional[str] = None) -> TranscriptionMemory:
    """Get the global transcription memory instance."""
    global _transcription_memory
    if _transcription_memory is None:
        _transcription_memory = TranscriptionMemory(memory_dir)
    return _transcription_memory


def get_model_cache() -> ModelCache:
    """Get the global model cache instance."""
    global _model_cache
    if _model_cache is None:
        _model_cache = ModelCache()
    return _model_cache
