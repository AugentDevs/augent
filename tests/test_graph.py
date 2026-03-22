"""Tests for the graph module — Obsidian graph view integration."""

import json
import os
import sqlite3
import tempfile

import pytest

from augent.graph import (
    _wikilink_name,
    _write_related_section,
    generate_mocs,
    migrate_markdown_files,
)
from augent.memory import TranscriptionMemory


class TestWikilinkName:
    """Tests for wikilink name extraction."""

    def test_basic_path(self):
        assert _wikilink_name("/path/to/My_File.md") == "My_File"

    def test_nested_path(self):
        assert _wikilink_name("/a/b/c/Travel_INSIDE_a_Black_Hole.md") == "Travel_INSIDE_a_Black_Hole"

    def test_no_extension(self):
        assert _wikilink_name("/path/to/file") == "file"

    def test_spaces_in_name(self):
        assert _wikilink_name("/path/My File Name.md") == "My File Name"


class TestWriteRelatedSection:
    """Tests for writing ## Related sections to .md files."""

    def test_appends_related_section(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, dir="/tmp"
        ) as f:
            f.write("---\ntitle: \"Test\"\ntype: transcription\n---\n\n# Test\n\n## Transcription\n\nSome text.\n")
            path = f.name

        related = [
            {"md_path": "/path/to/File_A.md", "shared_tags": ["AI"]},
            {"md_path": "/path/to/File_B.md", "shared_tags": []},
        ]
        _write_related_section(path, related)

        content = open(path).read()
        assert "## Related" in content
        assert "[[File_A]]" in content
        assert "[[File_B]]" in content
        assert "AI" in content  # shared tag annotation
        os.unlink(path)

    def test_replaces_existing_related_section(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, dir="/tmp"
        ) as f:
            f.write(
                "---\ntitle: \"Test\"\n---\n\n# Test\n\n## Transcription\n\nText.\n\n"
                "## Related\n\n- [[Old_Link]]\n"
            )
            path = f.name

        related = [{"md_path": "/path/New_Link.md", "shared_tags": []}]
        _write_related_section(path, related)

        content = open(path).read()
        assert "[[New_Link]]" in content
        assert "[[Old_Link]]" not in content
        # Should only have one Related section
        assert content.count("## Related") == 1
        os.unlink(path)

    def test_skips_nonexistent_file(self):
        # Should not raise
        _write_related_section("/tmp/nonexistent_file_xyz.md", [])


class TestBuildFrontmatter:
    """Tests for frontmatter generation."""

    def test_basic_frontmatter(self):
        fm = TranscriptionMemory._build_frontmatter(
            title="My Title",
            tags=["AI", "Science"],
            source="audio.webm",
            source_url="https://youtube.com/watch?v=xxx",
            duration="9:47",
            language="en",
            date="2026-03-22",
            type_="transcription",
        )
        assert fm.startswith("---\n")
        assert fm.endswith("---\n")
        assert 'title: "My Title"' in fm
        assert "  - AI" in fm
        assert "  - Science" in fm
        assert 'source: "audio.webm"' in fm
        assert 'source_url: "https://youtube.com/watch?v=xxx"' in fm
        assert 'duration: "9:47"' in fm
        assert "language: en" in fm
        assert "date: 2026-03-22" in fm
        assert "type: transcription" in fm

    def test_frontmatter_no_tags(self):
        fm = TranscriptionMemory._build_frontmatter(
            title="No Tags",
            language="en",
            date="2026-01-01",
        )
        assert "tags:" not in fm

    def test_frontmatter_with_extra(self):
        fm = TranscriptionMemory._build_frontmatter(
            title="Extra",
            type_="notes",
            extra={"style": "eye-candy", "source_transcription": '"[[My_File]]"'},
        )
        assert "style: eye-candy" in fm
        assert 'source_transcription: "[[My_File]]"' in fm

    def test_yaml_escape_quotes(self):
        fm = TranscriptionMemory._build_frontmatter(
            title='He said "hello" and left',
        )
        assert r'\"hello\"' in fm

    def test_yaml_escape_backslash(self):
        escaped = TranscriptionMemory._yaml_escape("path\\to\\file")
        assert escaped == "path\\\\to\\\\file"


class TestGenerateMocs:
    """Tests for MOC (Map of Content) generation."""

    @pytest.fixture
    def memory_with_tagged_transcriptions(self):
        """Create memory with multiple tagged transcriptions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = TranscriptionMemory(memory_dir=tmpdir)

            # Create 4 transcriptions, 3 tagged with "AI"
            for i in range(4):
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".mp3", dir="/tmp"
                ) as f:
                    f.write(f"fake audio content {i}".encode())
                    audio_path = f.name

                transcription = {
                    "text": f"Test content {i}",
                    "language": "en",
                    "duration": 60.0 * (i + 1),
                    "words": [],
                    "segments": [{"start": 0.0, "end": 5.0, "text": f"Text {i}"}],
                }
                memory.set(audio_path, "tiny", transcription)
                audio_hash = memory.hash_audio_file(audio_path)
                cache_key = f"{audio_hash}:tiny"

                if i < 3:  # First 3 get "AI" tag
                    memory.add_tags(cache_key, ["AI"], category="topic")
                if i == 0:  # First one also gets "Science"
                    memory.add_tags(cache_key, ["Science"], category="topic")

                os.unlink(audio_path)

            yield memory

    def test_generates_moc_for_qualifying_tags(self, memory_with_tagged_transcriptions):
        moc_paths = generate_mocs(memory_with_tagged_transcriptions, min_members=3)
        assert len(moc_paths) >= 1  # At least "AI" qualifies

        # Check MOC file content
        for path in moc_paths:
            content = open(path).read()
            assert content.startswith("---\n")
            assert "type: moc" in content
            assert "[[" in content  # Has wikilinks

    def test_skips_tags_below_threshold(self, memory_with_tagged_transcriptions):
        moc_paths = generate_mocs(memory_with_tagged_transcriptions, min_members=3)
        moc_names = [os.path.basename(p) for p in moc_paths]
        # "Science" only has 1 member, should not get a MOC
        assert not any("Science" in name for name in moc_names)

    def test_moc_has_frontmatter(self, memory_with_tagged_transcriptions):
        moc_paths = generate_mocs(memory_with_tagged_transcriptions, min_members=3)
        assert len(moc_paths) >= 1
        content = open(moc_paths[0]).read()
        assert 'title: "AI"' in content
        assert "tags:" in content
        assert "  - AI" in content
        assert "type: moc" in content


class TestMigrateMarkdownFiles:
    """Tests for migrating old-format .md files to YAML frontmatter."""

    @pytest.fixture
    def memory_with_old_format(self):
        """Create memory with an old-format .md file (no frontmatter)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = TranscriptionMemory(memory_dir=tmpdir)

            # Manually create an old-format file
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".mp3", dir="/tmp"
            ) as f:
                f.write(b"fake audio for migration test")
                audio_path = f.name

            audio_hash = memory.hash_audio_file(audio_path)
            cache_key = f"{audio_hash}:tiny"
            title = "Migration Test"

            # Write old-format .md manually
            sanitized = memory._sanitize_filename(title)
            md_path = memory.md_dir / f"{sanitized}.md"
            md_path.write_text(
                f"# {title}\n\n"
                f"**Source:** `test.mp3`  \n"
                f"**Duration:** 1:00  \n"
                f"**Language:** en  \n\n"
                f"---\n\n"
                f"## Transcription\n\n"
                f"**[0:00]** Hello world\n\n",
                encoding="utf-8",
            )

            # Insert DB row
            with sqlite3.connect(memory.db_path) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO transcriptions
                    (cache_key, audio_hash, model_size, language, duration,
                     text, words, segments, created_at, file_path, title, md_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cache_key,
                        audio_hash,
                        "tiny",
                        "en",
                        60.0,
                        "Hello world",
                        "[]",
                        json.dumps([{"start": 0.0, "end": 5.0, "text": "Hello world"}]),
                        1000000.0,
                        audio_path,
                        title,
                        str(md_path),
                    ),
                )
                conn.commit()

            # Add a tag
            memory.add_tags(cache_key, ["AI"])

            os.unlink(audio_path)
            yield memory, cache_key, md_path

    def test_migrates_old_format(self, memory_with_old_format):
        memory, cache_key, md_path = memory_with_old_format
        stats = migrate_markdown_files(memory)

        assert stats["migrated"] == 1
        assert stats["errors"] == 0

        content = md_path.read_text()
        assert content.startswith("---\n")
        assert "type: transcription" in content
        assert "  - AI" in content
        assert "## Transcription" in content
        assert "Hello world" in content

    def test_syncs_already_migrated(self, memory_with_old_format):
        memory, cache_key, md_path = memory_with_old_format

        # First migration
        migrate_markdown_files(memory)
        # Second run should sync, not re-migrate
        stats = migrate_markdown_files(memory)
        assert stats["synced"] == 1
        assert stats["migrated"] == 0

    def test_recreates_missing_md(self):
        """Test that missing .md files are recreated from DB data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = TranscriptionMemory(memory_dir=tmpdir)

            # Insert DB row with no .md file
            with sqlite3.connect(memory.db_path) as conn:
                conn.execute(
                    """INSERT INTO transcriptions
                    (cache_key, audio_hash, model_size, language, duration,
                     text, words, segments, created_at, file_path, title, md_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "fakehash:tiny",
                        "fakehash",
                        "tiny",
                        "en",
                        30.0,
                        "Recreated content",
                        "[]",
                        json.dumps([{"start": 0.0, "end": 5.0, "text": "Recreated content"}]),
                        1000000.0,
                        "/tmp/test.mp3",
                        "Recreated File",
                        "",  # Empty md_path
                    ),
                )
                conn.commit()

            stats = migrate_markdown_files(memory)
            assert stats["recreated"] == 1

            md_files = list(memory.md_dir.glob("*.md"))
            assert len(md_files) == 1
            content = md_files[0].read_text()
            assert content.startswith("---\n")
            assert "Recreated content" in content


class TestFrontmatterTagSync:
    """Tests specifically for the tag → frontmatter sync pipeline."""

    @pytest.fixture
    def memory_with_transcription(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = TranscriptionMemory(memory_dir=tmpdir)
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".mp3", dir="/tmp"
            ) as f:
                f.write(b"fake audio for frontmatter sync")
                audio_path = f.name

            transcription = {
                "text": "Frontmatter sync test content",
                "language": "fr",
                "duration": 300.0,
                "words": [],
                "segments": [{"start": 0.0, "end": 10.0, "text": "Bonjour le monde"}],
            }
            memory.set(audio_path, "tiny", transcription)
            audio_hash = memory.hash_audio_file(audio_path)
            cache_key = f"{audio_hash}:tiny"
            os.unlink(audio_path)
            yield memory, cache_key

    def test_frontmatter_preserves_body_on_tag_update(self, memory_with_transcription):
        memory, cache_key = memory_with_transcription
        memory.add_tags(cache_key, ["Music", "French"])

        md_files = list(memory.md_dir.glob("*.md"))
        content = md_files[0].read_text()

        # Body should still be intact
        assert "## Transcription" in content
        assert "Bonjour le monde" in content
        # Frontmatter should have tags
        assert "  - French" in content
        assert "  - Music" in content
        # Metadata should be preserved
        assert "language: fr" in content
        assert 'duration: "5:00"' in content

    def test_frontmatter_updates_correctly_on_multiple_tag_ops(self, memory_with_transcription):
        memory, cache_key = memory_with_transcription

        memory.add_tags(cache_key, ["A", "B", "C"])
        memory.remove_tags(cache_key, ["B"])
        memory.add_tags(cache_key, ["D"])

        md_files = list(memory.md_dir.glob("*.md"))
        content = md_files[0].read_text()
        assert "  - A" in content
        assert "  - C" in content
        assert "  - D" in content
        assert "  - B" not in content

    def test_sync_skips_missing_file(self, memory_with_transcription):
        memory, cache_key = memory_with_transcription
        # Delete the .md file
        md_files = list(memory.md_dir.glob("*.md"))
        for f in md_files:
            f.unlink()

        # Should not raise
        memory._sync_markdown_tags(cache_key)

    def test_sync_skips_old_format(self):
        """_sync_markdown_tags should skip files without YAML frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = TranscriptionMemory(memory_dir=tmpdir)
            md_path = memory.md_dir / "old_format.md"
            md_path.write_text("# Old\n\nNo frontmatter here.\n")

            with sqlite3.connect(memory.db_path) as conn:
                conn.execute(
                    """INSERT INTO transcriptions
                    (cache_key, audio_hash, model_size, language, duration,
                     text, words, segments, created_at, file_path, title, md_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "old:tiny", "old", "tiny", "en", 10.0,
                        "text", "[]", "[]", 1000000.0,
                        "/tmp/old.mp3", "Old", str(md_path),
                    ),
                )
                conn.commit()

            memory._sync_markdown_tags("old:tiny")
            # File should be unchanged (no frontmatter to update)
            content = md_path.read_text()
            assert content.startswith("# Old")
