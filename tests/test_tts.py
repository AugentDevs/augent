"""Tests for TTS markdown stripping, voice detection, and parameter validation."""

from augent.tts import LANG_MAP, SAMPLE_RATE, _strip_markdown


class TestStripMarkdownMetadata:
    """Test that metadata blocks at the top of notes are stripped."""

    def test_strips_title_and_metadata(self):
        text = "# My Notes\n**Source:** https://example.com\n**Duration:** 5:00\n---\nActual content here."
        result = _strip_markdown(text)
        assert "My Notes" not in result
        assert "Source:" not in result
        assert "Duration:" not in result
        assert "Actual content here." in result

    def test_strips_date_and_channel(self):
        text = "# Title\n**Date:** 2026-03-06\n**Channel:** SomeChannel\n---\nContent."
        result = _strip_markdown(text)
        assert "Date:" not in result
        assert "Channel:" not in result
        assert "Content." in result

    def test_strips_obsidian_embeds_in_metadata(self):
        text = "# Title\n![[audio.mp3]]\n> Tip text\n---\nReal content."
        result = _strip_markdown(text)
        assert "audio.mp3" not in result
        assert "Real content." in result


class TestStripMarkdownFormatting:
    """Test that markdown formatting is converted to plain text."""

    def test_strips_bold(self):
        result = _strip_markdown("---\n**bold text** here")
        assert "bold text here" in result
        assert "**" not in result

    def test_strips_italic(self):
        result = _strip_markdown("---\n*italic text* here")
        assert "italic text here" in result

    def test_strips_headers(self):
        result = _strip_markdown("---\n## Section Title\nParagraph text.")
        assert "Section Title" in result
        assert "##" not in result

    def test_strips_bullet_points(self):
        result = _strip_markdown("---\n- First item\n- Second item")
        assert "First item" in result
        assert "Second item" in result
        assert "- " not in result

    def test_strips_links(self):
        result = _strip_markdown("---\n[click here](https://example.com)")
        assert "click here" in result
        assert "https://example.com" not in result

    def test_strips_inline_code(self):
        result = _strip_markdown("---\nRun `pip install augent` now")
        assert "pip install augent" in result
        assert "`" not in result

    def test_strips_wiki_links(self):
        result = _strip_markdown("---\nSee [[Some Page]] for details")
        assert "Some Page" in result
        assert "[[" not in result

    def test_strips_wiki_links_with_display(self):
        result = _strip_markdown("---\nSee [[file|Display Name]] for details")
        assert "Display Name" in result
        assert "file" not in result.split("Display Name")[0]

    def test_strips_checklist_syntax(self):
        result = _strip_markdown("---\n- [x] Done task\n- [ ] Open task")
        assert "Done task" in result
        assert "Open task" in result
        assert "[x]" not in result
        assert "[ ]" not in result


class TestStripMarkdownTimestamps:
    """Test that timestamps are handled correctly for natural speech."""

    def test_strips_inline_timestamps(self):
        result = _strip_markdown("---\nHe mentioned this at 5:30 in the talk")
        assert "5:30" not in result
        assert "mentioned this" in result

    def test_strips_header_timestamp_prefix(self):
        result = _strip_markdown("---\n## 5:00 — The Miami Side Quest")
        assert "The Miami Side Quest" in result
        assert "5:00" not in result

    def test_strips_standalone_timestamp_lines(self):
        result = _strip_markdown("---\nSome content\n> — *2:15*\nMore content")
        assert "2:15" not in result
        assert "Some content" in result
        assert "More content" in result


class TestStripMarkdownTables:
    """Test table handling."""

    def test_strips_table_separators(self):
        result = _strip_markdown("---\n| Header |\n|---|\n| Data |")
        assert "---" not in result or result.count("---") == 0

    def test_extracts_table_cell_contents(self):
        result = _strip_markdown(
            "---\n| Topic | Description |\n|---|---|\n| AI | Machine learning tools |"
        )
        assert "Machine learning tools" in result

    def test_skips_timestamp_only_cells(self):
        result = _strip_markdown("---\n| 5:00 | Some topic |\n|---|---|")
        assert "Some topic" in result


class TestStripMarkdownCallouts:
    """Test Obsidian callout handling."""

    def test_extracts_callout_title_text(self):
        result = _strip_markdown("---\nSome content.\n> [!tip] Important insight here")
        assert "Important insight here" in result
        assert "[!tip]" not in result

    def test_strips_empty_callout(self):
        result = _strip_markdown("---\n> [!note]")
        assert "[!note]" not in result


class TestStripMarkdownEmoji:
    """Test emoji and decorative character removal."""

    def test_strips_emoji(self):
        result = _strip_markdown("---\nGreat point 🎙 about audio")
        assert "🎙" not in result
        assert "Great point" in result
        assert "about audio" in result

    def test_strips_decorative_chars(self):
        result = _strip_markdown("---\n✦ Key takeaway ✦")
        assert "✦" not in result
        assert "Key takeaway" in result


class TestStripMarkdownEdgeCases:
    def test_empty_string(self):
        assert _strip_markdown("") == ""

    def test_only_metadata(self):
        result = _strip_markdown("# Title\n**Source:** url\n**Duration:** 5:00\n---")
        assert result == ""

    def test_collapses_multiple_blank_lines(self):
        result = _strip_markdown("---\nFirst\n\n\n\n\nSecond")
        assert "\n\n\n" not in result
        assert "First" in result
        assert "Second" in result

    def test_strips_trailing_em_dashes(self):
        result = _strip_markdown("---\nSome text —")
        assert result.endswith("Some text")


class TestLangMap:
    def test_all_voice_prefixes_mapped(self):
        expected_prefixes = {"a", "b", "e", "f", "h", "i", "j", "p", "z"}
        assert set(LANG_MAP.keys()) == expected_prefixes

    def test_american_english_is_default(self):
        assert LANG_MAP["a"] == "American English"


class TestSampleRate:
    def test_sample_rate_is_24khz(self):
        assert SAMPLE_RATE == 24000
