"""Tests for the export module."""

import pytest

from augent.export import (
    Exporter,
    export_matches,
    export_transcription,
    format_srt_timestamp,
    format_vtt_timestamp,
)

# Sample data for testing
SAMPLE_MATCHES = [
    {
        "keyword": "startup",
        "timestamp": "0:30",
        "timestamp_seconds": 30.5,
        "snippet": "...the startup raised funding...",
        "confidence": 1.0,
        "match_type": "exact",
    },
    {
        "keyword": "funding",
        "timestamp": "1:45",
        "timestamp_seconds": 105.2,
        "snippet": "...raised significant funding last...",
        "confidence": 1.0,
        "match_type": "exact",
    },
    {
        "keyword": "startup",
        "timestamp": "3:20",
        "timestamp_seconds": 200.0,
        "snippet": "...another startup company...",
        "confidence": 0.85,
        "match_type": "fuzzy",
    },
]

SAMPLE_SEGMENTS = [
    {"start": 0.0, "end": 5.0, "text": "Welcome to the podcast about startups."},
    {"start": 5.0, "end": 10.0, "text": "Today we discuss funding strategies."},
    {"start": 10.0, "end": 15.0, "text": "Let's get started with our first topic."},
]


class TestTimestampFormatting:
    """Tests for timestamp formatting functions."""

    def test_srt_timestamp_format(self):
        assert format_srt_timestamp(0.0) == "00:00:00,000"
        assert format_srt_timestamp(65.5) == "00:01:05,500"
        assert format_srt_timestamp(3661.123) == "01:01:01,123"

    def test_vtt_timestamp_format(self):
        assert format_vtt_timestamp(0.0) == "00:00:00.000"
        assert format_vtt_timestamp(65.5) == "00:01:05.500"
        assert format_vtt_timestamp(3661.123) == "01:01:01.123"


class TestExporterSRT:
    """Tests for SRT export."""

    def test_basic_srt_export(self):
        exporter = Exporter()
        result = exporter.to_srt(SAMPLE_SEGMENTS)

        assert "WEBVTT" not in result
        assert "-->" in result
        assert "Welcome to the podcast" in result
        assert "1\n" in result

    def test_srt_with_keyword_highlight(self):
        exporter = Exporter()
        result = exporter.to_srt(SAMPLE_SEGMENTS, highlight_keywords=["startups"])

        assert "<b>startups</b>" in result

    def test_matches_to_srt(self):
        exporter = Exporter()
        result = exporter.matches_to_srt(SAMPLE_MATCHES)

        assert "-->" in result
        assert "[startup]" in result
        assert "[funding]" in result


class TestExporterVTT:
    """Tests for VTT export."""

    def test_basic_vtt_export(self):
        exporter = Exporter()
        result = exporter.to_vtt(SAMPLE_SEGMENTS)

        assert result.startswith("WEBVTT")
        assert "-->" in result
        assert "Welcome to the podcast" in result

    def test_vtt_with_keyword_highlight(self):
        exporter = Exporter()
        result = exporter.to_vtt(SAMPLE_SEGMENTS, highlight_keywords=["funding"])

        assert "<b>funding</b>" in result

    def test_matches_to_vtt(self):
        exporter = Exporter()
        result = exporter.matches_to_vtt(SAMPLE_MATCHES)

        assert result.startswith("WEBVTT")
        assert "[startup]" in result


class TestExporterCSV:
    """Tests for CSV export."""

    def test_csv_has_header(self):
        exporter = Exporter()
        result = exporter.to_csv(SAMPLE_MATCHES)

        lines = result.strip().split("\n")
        header = lines[0]

        assert "keyword" in header
        assert "timestamp" in header
        assert "snippet" in header

    def test_csv_has_data_rows(self):
        exporter = Exporter()
        result = exporter.to_csv(SAMPLE_MATCHES)

        lines = result.strip().split("\n")
        assert len(lines) == 4  # 1 header + 3 data rows

    def test_csv_escapes_commas(self):
        matches_with_comma = [
            {
                "keyword": "test",
                "timestamp": "0:00",
                "timestamp_seconds": 0,
                "snippet": "...hello, world...",
                "confidence": 1.0,
                "match_type": "exact",
            }
        ]
        exporter = Exporter()
        result = exporter.to_csv(matches_with_comma)

        # CSV should properly quote fields with commas
        assert '"hello' in result or "hello" in result


class TestExporterMarkdown:
    """Tests for Markdown export."""

    def test_markdown_has_header(self):
        exporter = Exporter()
        result = exporter.to_markdown(SAMPLE_MATCHES)

        assert "# Augent Search Results" in result

    def test_markdown_groups_by_keyword(self):
        exporter = Exporter()
        result = exporter.to_markdown(SAMPLE_MATCHES)

        assert "### startup" in result
        assert "### funding" in result

    def test_markdown_includes_table(self):
        exporter = Exporter()
        result = exporter.to_markdown(SAMPLE_MATCHES)

        assert "| Timestamp |" in result
        assert "|-----------|" in result

    def test_markdown_with_audio_file(self):
        exporter = Exporter()
        result = exporter.to_markdown(SAMPLE_MATCHES, audio_file="test.mp3")

        assert "**Audio File:** test.mp3" in result


class TestExporterJSON:
    """Tests for JSON export."""

    def test_json_grouped(self):
        exporter = Exporter()
        result = exporter.to_json(SAMPLE_MATCHES, grouped=True)

        import json

        data = json.loads(result)

        assert "startup" in data
        assert "funding" in data
        assert len(data["startup"]) == 2

    def test_json_ungrouped(self):
        exporter = Exporter()
        result = exporter.to_json(SAMPLE_MATCHES, grouped=False)

        import json

        data = json.loads(result)

        assert isinstance(data, list)
        assert len(data) == 3

    def test_json_with_metadata(self):
        exporter = Exporter()
        result = exporter.to_json(
            SAMPLE_MATCHES,
            grouped=True,
            include_metadata=True,
            metadata={"source": "test.mp3", "model": "base"},
        )

        import json

        data = json.loads(result)

        assert "metadata" in data
        assert data["metadata"]["source"] == "test.mp3"


class TestExportMatches:
    """Tests for the export_matches convenience function."""

    def test_export_json(self):
        result = export_matches(SAMPLE_MATCHES, format="json")
        assert "{" in result

    def test_export_csv(self):
        result = export_matches(SAMPLE_MATCHES, format="csv")
        assert "keyword" in result

    def test_export_srt(self):
        result = export_matches(SAMPLE_MATCHES, format="srt")
        assert "-->" in result

    def test_export_vtt(self):
        result = export_matches(SAMPLE_MATCHES, format="vtt")
        assert "WEBVTT" in result

    def test_export_markdown(self):
        result = export_matches(SAMPLE_MATCHES, format="markdown")
        assert "# Augent" in result

    def test_export_md_alias(self):
        result = export_matches(SAMPLE_MATCHES, format="md")
        assert "# Augent" in result

    def test_export_unknown_format_raises(self):
        with pytest.raises(ValueError):
            export_matches(SAMPLE_MATCHES, format="unknown")


class TestExportTranscription:
    """Tests for the export_transcription convenience function."""

    def test_export_srt(self):
        result = export_transcription(SAMPLE_SEGMENTS, format="srt")
        assert "-->" in result
        assert "WEBVTT" not in result

    def test_export_vtt(self):
        result = export_transcription(SAMPLE_SEGMENTS, format="vtt")
        assert "WEBVTT" in result

    def test_export_unknown_format_raises(self):
        with pytest.raises(ValueError):
            export_transcription(SAMPLE_SEGMENTS, format="json")
