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

            conn.commit()

    @staticmethod
    def hash_audio_file(file_path: str) -> str:
        """
        Generate a hash of the audio file content.
        Uses SHA256 for reliable uniqueness.
        """
        hasher = hashlib.sha256()
        home = os.path.abspath(os.path.expanduser("~"))
        resolved = os.path.normpath(os.path.abspath(file_path))
        if not resolved.startswith(home + os.sep) and not resolved.startswith(
            "/tmp" + os.sep
        ):
            raise ValueError(
                f"Access denied: path must be under home directory or /tmp: {resolved}"
            )
        if not os.path.isfile(resolved):
            raise FileNotFoundError(f"Audio file not found: {resolved}")
        with open(resolved, "rb") as f:
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

            return {
                "entries": count,
                "embedding_entries": embedding_count,
                "diarization_entries": diarization_count,
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
                    mins = int(duration // 60)
                    secs = int(duration % 60)

                    entries.append(
                        {
                            "cache_key": row["cache_key"],
                            "title": row["title"]
                            or os.path.basename(row["file_path"] or ""),
                            "duration": duration,
                            "duration_formatted": f"{mins}:{secs:02d}",
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
