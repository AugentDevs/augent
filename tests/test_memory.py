"""Tests for the memory module."""

import os
import sqlite3
import tempfile

import pytest

from augent.memory import (
    MemorizedTranscription,
    ModelCache,
    TranscriptionMemory,
)


class TestTranscriptionMemory:
    """Tests for TranscriptionMemory."""

    @pytest.fixture
    def temp_memory(self):
        """Create a temporary memory directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = TranscriptionMemory(memory_dir=tmpdir)
            yield memory

    @pytest.fixture
    def sample_audio_file(self):
        """Create a temporary file to simulate an audio file."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", dir="/tmp") as f:
            f.write(b"fake audio content for testing")
            yield f.name
        os.unlink(f.name)

    def test_memory_miss_returns_none(self, temp_memory, sample_audio_file):
        result = temp_memory.get(sample_audio_file, "base")
        assert result is None

    def test_memory_set_and_get(self, temp_memory, sample_audio_file):
        transcription = {
            "text": "Hello world",
            "language": "en",
            "duration": 10.5,
            "words": [{"word": "Hello", "start": 0.0, "end": 0.5}],
            "segments": [{"start": 0.0, "end": 1.0, "text": "Hello world"}],
        }

        temp_memory.set(sample_audio_file, "base", transcription)
        result = temp_memory.get(sample_audio_file, "base")

        assert result is not None
        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration == 10.5
        assert len(result.words) == 1
        assert len(result.segments) == 1

    def test_different_models_stored_separately(self, temp_memory, sample_audio_file):
        trans_base = {
            "text": "Base transcription",
            "language": "en",
            "duration": 10.0,
            "words": [],
            "segments": [],
        }
        trans_large = {
            "text": "Large transcription",
            "language": "en",
            "duration": 10.0,
            "words": [],
            "segments": [],
        }

        temp_memory.set(sample_audio_file, "base", trans_base)
        temp_memory.set(sample_audio_file, "large", trans_large)

        result_base = temp_memory.get(sample_audio_file, "base")
        result_large = temp_memory.get(sample_audio_file, "large")

        assert result_base.text == "Base transcription"
        assert result_large.text == "Large transcription"

    def test_chronological_neighbor_link(self, temp_memory):
        """New transcriptions link to the most recent previous one to prevent orphans."""
        # Create first transcription
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", dir="/tmp") as f:
            f.write(b"first audio file")
            path1 = f.name

        temp_memory.set(path1, "tiny", {
            "text": "First", "language": "en", "duration": 10.0,
            "words": [], "segments": [{"start": 0.0, "end": 10.0, "text": "First"}],
        })
        first_name = temp_memory._sanitize_filename(
            temp_memory._title_from_path(path1)
        )
        os.unlink(path1)

        # Create second transcription
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", dir="/tmp") as f:
            f.write(b"second audio file")
            path2 = f.name

        temp_memory.set(path2, "tiny", {
            "text": "Second", "language": "en", "duration": 15.0,
            "words": [], "segments": [{"start": 0.0, "end": 15.0, "text": "Second"}],
        })
        second_name = temp_memory._sanitize_filename(
            temp_memory._title_from_path(path2)
        )
        os.unlink(path2)

        # Second file should contain a [[wikilink]] to the first
        second_md = temp_memory.md_dir / f"{second_name}.md"
        assert second_md.exists()
        second_content = second_md.read_text()
        assert f"[[{first_name}]]" in second_content
        assert "## Related" in second_content

    def test_chronological_neighbor_no_duplicate(self, temp_memory):
        """Neighbor link should not duplicate if file already links to it."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", dir="/tmp") as f:
            f.write(b"audio A")
            path1 = f.name
        temp_memory.set(path1, "tiny", {
            "text": "A", "language": "en", "duration": 5.0,
            "words": [], "segments": [],
        })
        first_name = temp_memory._sanitize_filename(
            temp_memory._title_from_path(path1)
        )
        os.unlink(path1)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", dir="/tmp") as f:
            f.write(b"audio B")
            path2 = f.name
        temp_memory.set(path2, "tiny", {
            "text": "B", "language": "en", "duration": 5.0,
            "words": [], "segments": [],
        })

        # Set again (re-transcribe) — should not duplicate the link
        temp_memory.set(path2, "tiny", {
            "text": "B updated", "language": "en", "duration": 5.0,
            "words": [], "segments": [],
        })
        second_name = temp_memory._sanitize_filename(
            temp_memory._title_from_path(path2)
        )
        os.unlink(path2)

        second_md = temp_memory.md_dir / f"{second_name}.md"
        second_content = second_md.read_text()
        assert second_content.count(f"[[{first_name}]]") == 1

    def test_clear_memory(self, temp_memory, sample_audio_file):
        transcription = {
            "text": "Test",
            "language": "en",
            "duration": 5.0,
            "words": [],
            "segments": [],
        }

        temp_memory.set(sample_audio_file, "base", transcription)
        assert temp_memory.get(sample_audio_file, "base") is not None

        count = temp_memory.clear()
        assert count == 1
        assert temp_memory.get(sample_audio_file, "base") is None

    def test_stats(self, temp_memory, sample_audio_file):
        transcription = {
            "text": "Test",
            "language": "en",
            "duration": 100.0,
            "words": [],
            "segments": [],
        }

        # Empty memory
        stats = temp_memory.stats()
        assert stats["entries"] == 0

        # After adding
        temp_memory.set(sample_audio_file, "base", transcription)
        stats = temp_memory.stats()
        assert stats["entries"] == 1
        assert stats["total_audio_duration_hours"] > 0
        assert "titles" in stats
        assert len(stats["titles"]) == 1
        assert "md_dir" in stats

    def test_hash_audio_file(self, sample_audio_file):
        hash1 = TranscriptionMemory.hash_audio_file(sample_audio_file)
        hash2 = TranscriptionMemory.hash_audio_file(sample_audio_file)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    # --- Title and markdown tests ---

    def test_set_populates_title(self, temp_memory, sample_audio_file):
        transcription = {
            "text": "Test",
            "language": "en",
            "duration": 5.0,
            "words": [],
            "segments": [],
        }
        temp_memory.set(sample_audio_file, "base", transcription)
        result = temp_memory.get(sample_audio_file, "base")
        assert result is not None
        assert result.title != ""

    def test_set_creates_markdown_file(self, temp_memory, sample_audio_file):
        transcription = {
            "text": "Hello world this is a test",
            "language": "en",
            "duration": 10.5,
            "words": [{"word": "Hello", "start": 0.0, "end": 0.5}],
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "Hello world this is a test"}
            ],
        }
        temp_memory.set(sample_audio_file, "base", transcription)

        md_files = list(temp_memory.md_dir.glob("*.md"))
        assert len(md_files) == 1

        content = md_files[0].read_text()
        assert "Hello world" in content
        assert "[0:00]" in content

    def test_markdown_has_yaml_frontmatter(self, temp_memory, sample_audio_file):
        transcription = {
            "text": "Test content",
            "language": "en",
            "duration": 125.0,
            "words": [],
            "segments": [{"start": 0.0, "end": 5.0, "text": "Test content"}],
        }
        temp_memory.set(sample_audio_file, "base", transcription)

        md_files = list(temp_memory.md_dir.glob("*.md"))
        content = md_files[0].read_text()
        assert content.startswith("---\n")
        assert "\n---\n" in content[4:]

    def test_markdown_frontmatter_contains_metadata(self, temp_memory, sample_audio_file):
        transcription = {
            "text": "Test content",
            "language": "en",
            "duration": 125.0,
            "words": [],
            "segments": [{"start": 0.0, "end": 5.0, "text": "Test content"}],
        }
        temp_memory.set(sample_audio_file, "base", transcription)

        md_files = list(temp_memory.md_dir.glob("*.md"))
        content = md_files[0].read_text()
        assert 'duration: "2:05"' in content
        assert "language: en" in content
        assert "type: transcription" in content
        assert "date: " in content

    def test_markdown_frontmatter_contains_title(self, temp_memory, sample_audio_file):
        transcription = {
            "text": "Test",
            "language": "en",
            "duration": 5.0,
            "words": [],
            "segments": [],
        }
        temp_memory.set(sample_audio_file, "base", transcription)

        md_files = list(temp_memory.md_dir.glob("*.md"))
        content = md_files[0].read_text()
        assert "title: " in content

    def test_get_by_title(self, temp_memory, sample_audio_file):
        transcription = {
            "text": "Test",
            "language": "en",
            "duration": 5.0,
            "words": [],
            "segments": [],
        }
        temp_memory.set(sample_audio_file, "base", transcription)

        # The title is derived from the temp file name
        title = TranscriptionMemory._title_from_path(sample_audio_file)
        results = temp_memory.get_by_title(title[:5])
        assert len(results) >= 1
        assert results[0].text == "Test"

    def test_get_by_title_no_match(self, temp_memory):
        results = temp_memory.get_by_title("nonexistent_title_xyz")
        assert len(results) == 0

    def test_list_all_empty(self, temp_memory):
        entries = temp_memory.list_all()
        assert entries == []

    def test_list_all_with_entries(self, temp_memory, sample_audio_file):
        transcription = {
            "text": "Test",
            "language": "en",
            "duration": 120.0,
            "words": [],
            "segments": [],
        }
        temp_memory.set(sample_audio_file, "base", transcription)

        entries = temp_memory.list_all()
        assert len(entries) == 1
        assert "title" in entries[0]
        assert entries[0]["duration_formatted"] == "2:00"
        assert "md_path" in entries[0]
        assert "date" in entries[0]

    def test_clear_removes_markdown_files(self, temp_memory, sample_audio_file):
        transcription = {
            "text": "Test",
            "language": "en",
            "duration": 5.0,
            "words": [],
            "segments": [{"start": 0.0, "end": 5.0, "text": "Test"}],
        }
        temp_memory.set(sample_audio_file, "base", transcription)

        md_files = list(temp_memory.md_dir.glob("*.md"))
        assert len(md_files) == 1

        temp_memory.clear()

        md_files = list(temp_memory.md_dir.glob("*.md"))
        assert len(md_files) == 0

    def test_db_migration_adds_columns(self):
        """Test that opening a DB without title/md_path columns adds them."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "transcriptions.db")

            # Create a DB with the old schema (no title, no md_path)
            with sqlite3.connect(db_path) as conn:
                conn.execute("""
                    CREATE TABLE transcriptions (
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
                    INSERT INTO transcriptions VALUES
                    ('hash1:tiny', 'hash1', 'tiny', 'en', 60.0,
                     'old text', '[]', '[]', 1000000.0, '/old/path.mp3')
                """)
                conn.commit()

            # Now open with TranscriptionMemory which triggers migration
            memory = TranscriptionMemory(memory_dir=tmpdir)

            # Verify old data still accessible
            stats = memory.stats()
            assert stats["entries"] == 1

            # Verify new columns exist (list_all uses them)
            entries = memory.list_all()
            assert len(entries) == 1
            # Old row has empty title in DB, list_all falls back to basename
            assert entries[0]["title"] == "path.mp3"


class TestTitleDerivation:
    """Tests for title extraction and sanitization."""

    def test_title_from_simple_path(self):
        title = TranscriptionMemory._title_from_path("/path/to/My Podcast Episode.mp3")
        assert title == "My Podcast Episode"

    def test_title_from_path_strips_extension(self):
        title = TranscriptionMemory._title_from_path("/downloads/audio.webm")
        assert title == "audio"

    def test_title_preserves_spaces(self):
        title = TranscriptionMemory._title_from_path("/path/How to Build a Startup.mp3")
        assert title == "How to Build a Startup"

    def test_sanitize_filename_removes_special_chars(self):
        sanitized = TranscriptionMemory._sanitize_filename("Hello: World! (2024) [HD]")
        assert ":" not in sanitized
        assert "!" not in sanitized
        assert "[" not in sanitized
        assert len(sanitized) > 0

    def test_sanitize_filename_truncates_long_titles(self):
        long_title = "A" * 300
        sanitized = TranscriptionMemory._sanitize_filename(long_title)
        assert len(sanitized) <= 200

    def test_sanitize_filename_handles_empty(self):
        sanitized = TranscriptionMemory._sanitize_filename("")
        assert sanitized == "untitled"

    def test_sanitize_filename_collapses_underscores(self):
        sanitized = TranscriptionMemory._sanitize_filename("hello___world   test")
        assert "__" not in sanitized
        assert "  " not in sanitized


class TestTagging:
    """Tests for tag CRUD and auto-tagging."""

    @pytest.fixture
    def temp_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = TranscriptionMemory(memory_dir=tmpdir)
            yield memory

    @pytest.fixture
    def stored_transcription(self, temp_memory):
        """Store a sample transcription and return its cache_key."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", dir="/tmp") as f:
            f.write(b"fake audio for tag testing")
            audio_path = f.name

        transcription = {
            "text": "Hello world test content",
            "language": "en",
            "duration": 10.0,
            "words": [],
            "segments": [],
        }
        temp_memory.set(audio_path, "tiny", transcription)
        audio_hash = TranscriptionMemory.hash_audio_file(audio_path)
        cache_key = f"{audio_hash}:tiny"
        os.unlink(audio_path)
        return cache_key

    def test_add_tags(self, temp_memory, stored_transcription):
        added = temp_memory.add_tags(stored_transcription, ["AI", "productivity"])
        assert len(added) == 2
        assert added[0]["name"] == "AI"

    def test_get_tags(self, temp_memory, stored_transcription):
        temp_memory.add_tags(stored_transcription, ["AI", "testing"])
        tags = temp_memory.get_tags(stored_transcription)
        names = [t["name"] for t in tags]
        assert "AI" in names
        assert "testing" in names

    def test_remove_tags(self, temp_memory, stored_transcription):
        temp_memory.add_tags(stored_transcription, ["AI", "testing"])
        temp_memory.remove_tags(stored_transcription, ["AI"])
        tags = temp_memory.get_tags(stored_transcription)
        names = [t["name"] for t in tags]
        assert "AI" not in names
        assert "testing" in names

    def test_filter_by_tag(self, temp_memory, stored_transcription):
        temp_memory.add_tags(stored_transcription, ["unique_tag"])
        results = temp_memory.filter_by_tag("unique_tag")
        assert len(results) == 1
        assert results[0]["cache_key"] == stored_transcription

    def test_filter_by_tag_empty(self, temp_memory):
        results = temp_memory.filter_by_tag("nonexistent")
        assert results == []

    def test_add_duplicate_tags_idempotent(self, temp_memory, stored_transcription):
        temp_memory.add_tags(stored_transcription, ["AI"])
        temp_memory.add_tags(stored_transcription, ["AI"])
        tags = temp_memory.get_tags(stored_transcription)
        ai_tags = [t for t in tags if t["name"] == "AI"]
        assert len(ai_tags) == 1

    def test_auto_tag_extracts_capitalized_phrases(
        self, temp_memory, stored_transcription
    ):
        text = (
            "Today we talked to Greg Eisenberg about startups. "
            "Greg Eisenberg shared his thoughts on building products. "
            "Later Greg Eisenberg discussed growth strategies with the team. "
            "The audience loved hearing from Greg Eisenberg on this topic."
        )
        extracted = temp_memory.auto_tag(stored_transcription, text)
        assert extracted == []  # auto_tag is deprecated, always returns []

    def test_auto_tag_skips_short_text(self, temp_memory, stored_transcription):
        extracted = temp_memory.auto_tag(stored_transcription, "hi")
        assert extracted == []

    def test_auto_tag_frequency_mode_for_lowercase(
        self, temp_memory, stored_transcription
    ):
        text = " ".join(
            ["obsidian"] * 20 + ["the"] * 50 + ["random"] * 2 + ["filler"] * 100
        )
        extracted = temp_memory.auto_tag(stored_transcription, text)
        assert extracted == []  # auto_tag is deprecated, always returns []

    def test_add_tags_syncs_to_markdown(self, temp_memory):
        """Test that adding tags updates the .md file's YAML frontmatter."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", dir="/tmp") as f:
            f.write(b"fake audio for tag sync test")
            audio_path = f.name

        transcription = {
            "text": "Test content for tag sync",
            "language": "en",
            "duration": 10.0,
            "words": [],
            "segments": [{"start": 0.0, "end": 10.0, "text": "Test content"}],
        }
        temp_memory.set(audio_path, "tiny", transcription)
        audio_hash = TranscriptionMemory.hash_audio_file(audio_path)
        cache_key = f"{audio_hash}:tiny"

        # Add tags
        temp_memory.add_tags(cache_key, ["AI", "Startups"])

        # Read the .md file and check frontmatter contains tags
        md_files = list(temp_memory.md_dir.glob("*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text()
        assert "tags:" in content
        assert "  - AI" in content
        assert "  - Startups" in content
        os.unlink(audio_path)

    def test_remove_tags_syncs_to_markdown(self, temp_memory):
        """Test that removing tags updates the .md file's YAML frontmatter."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", dir="/tmp") as f:
            f.write(b"fake audio for tag remove sync test")
            audio_path = f.name

        transcription = {
            "text": "Test content for remove sync",
            "language": "en",
            "duration": 10.0,
            "words": [],
            "segments": [{"start": 0.0, "end": 10.0, "text": "Test content"}],
        }
        temp_memory.set(audio_path, "tiny", transcription)
        audio_hash = TranscriptionMemory.hash_audio_file(audio_path)
        cache_key = f"{audio_hash}:tiny"

        # Add then remove
        temp_memory.add_tags(cache_key, ["AI", "Startups", "Health"])
        temp_memory.remove_tags(cache_key, ["Startups"])

        md_files = list(temp_memory.md_dir.glob("*.md"))
        content = md_files[0].read_text()
        assert "  - AI" in content
        assert "  - Health" in content
        assert "  - Startups" not in content
        os.unlink(audio_path)

    def test_clear_removes_tags(self, temp_memory, stored_transcription):
        temp_memory.add_tags(stored_transcription, ["AI"])
        temp_memory.clear()
        tags = temp_memory.get_tags(stored_transcription)
        assert tags == []

    def test_stats_includes_tag_count(self, temp_memory, stored_transcription):
        temp_memory.add_tags(stored_transcription, ["tag1", "tag2"])
        stats = temp_memory.stats()
        assert stats["tag_count"] == 2


class TestModelCache:
    """Tests for ModelCache (singleton pattern)."""

    def test_singleton_pattern(self):
        cache1 = ModelCache()
        cache2 = ModelCache()
        assert cache1 is cache2

    def test_loaded_models_initially_empty(self):
        cache = ModelCache()
        cache.clear()
        assert cache.loaded_models() == []

    def test_clear(self):
        cache = ModelCache()
        cache.clear()
        assert cache.loaded_models() == []


class TestMemorizedTranscription:
    """Tests for MemorizedTranscription dataclass."""

    def test_dataclass_creation(self):
        stored = MemorizedTranscription(
            audio_hash="abc123",
            model_size="base",
            language="en",
            duration=60.0,
            text="Hello world",
            words=[],
            segments=[],
            created_at=1234567890.0,
            file_path="/path/to/audio.mp3",
        )

        assert stored.audio_hash == "abc123"
        assert stored.model_size == "base"
        assert stored.language == "en"
        assert stored.duration == 60.0
        assert stored.text == "Hello world"
        assert stored.title == ""  # Default

    def test_dataclass_with_title(self):
        stored = MemorizedTranscription(
            audio_hash="abc123",
            model_size="base",
            language="en",
            duration=60.0,
            text="Hello world",
            words=[],
            segments=[],
            created_at=1234567890.0,
            file_path="/path/to/audio.mp3",
            title="My Podcast",
        )

        assert stored.title == "My Podcast"
