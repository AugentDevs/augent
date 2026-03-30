"""
Tests for the visual tool handler and helper functions.

Covers: mode detection, parameter validation, _score_visual_necessity patterns,
clear mode, assist mode gap clustering, and handle_visual error paths.
All subprocess/external calls are mocked.
"""

import os
import tempfile
from unittest import mock

import pytest

from augent.mcp import (
    _score_visual_necessity,
    handle_visual,
)

# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


class TestVisualValidation:
    """Tests for handle_visual input validation."""

    def test_missing_video_and_url_raises(self):
        with pytest.raises(ValueError, match="Provide video_path.*or url"):
            handle_visual({})

    def test_missing_video_file_raises(self):
        with pytest.raises(FileNotFoundError, match="Video file not found"):
            handle_visual({"video_path": "/nonexistent/video.mp4"})

    def test_max_frames_below_one_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00")
            tmp = f.name
        try:
            with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                with pytest.raises(ValueError, match="max_frames must be at least 1"):
                    handle_visual(
                        {
                            "video_path": tmp,
                            "query": "test",
                            "max_frames": 0,
                        }
                    )
        finally:
            os.unlink(tmp)

    def test_no_mode_specified_raises(self):
        """Must provide query, timestamps, auto, or assist."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00")
            tmp = f.name
        try:
            mock_transcribe = mock.MagicMock(
                return_value={"segments": [{"start": 0, "end": 5, "text": "hello"}]}
            )
            with (
                mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"),
                mock.patch(
                    "subprocess.run",
                    return_value=mock.Mock(returncode=0, stdout="120.0\n", stderr=""),
                ),
                mock.patch("augent.core.transcribe_audio", mock_transcribe),
                mock.patch.dict(
                    "sys.modules",
                    {"augent.core": mock.MagicMock(transcribe_audio=mock_transcribe)},
                ),
            ):
                with pytest.raises(ValueError, match="Provide one of"):
                    handle_visual({"video_path": tmp})
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# _score_visual_necessity
# ---------------------------------------------------------------------------


class TestScoreVisualNecessity:
    """Tests for the pattern-matching + heuristic scoring function."""

    def test_explicit_visual_reference_scores_high(self):
        segments = [
            {
                "start": 0,
                "end": 5,
                "text": "As you can see on the screen, the button is here.",
            },
        ]
        scored = _score_visual_necessity(segments)
        assert len(scored) == 1
        idx, score, reason = scored[0]
        assert score >= 0.5

    def test_ui_action_scores_above_baseline(self):
        segments = [
            {"start": 0, "end": 5, "text": "Click on the submit button to continue."},
        ]
        scored = _score_visual_necessity(segments)
        assert len(scored) == 1
        _, score, _ = scored[0]
        assert score > 0.3

    def test_plain_speech_scores_low(self):
        segments = [
            {"start": 0, "end": 5, "text": "I think the weather is nice today."},
        ]
        scored = _score_visual_necessity(segments)
        assert len(scored) == 1
        _, score, _ = scored[0]
        assert score < 0.4

    def test_multiple_patterns_compound(self):
        """A segment with multiple visual cues should score >= a single cue."""
        single = [{"start": 0, "end": 5, "text": "Click on the button."}]
        multi = [
            {
                "start": 0,
                "end": 5,
                "text": "Click on the button in the top right corner of the dashboard.",
            }
        ]
        scored_single = _score_visual_necessity(single)
        scored_multi = _score_visual_necessity(multi)
        assert scored_multi[0][1] >= scored_single[0][1]

    def test_empty_segments_returns_empty(self):
        scored = _score_visual_necessity([])
        assert scored == []

    def test_returns_score_for_every_segment(self):
        segments = [
            {"start": 0, "end": 5, "text": "first segment"},
            {"start": 5, "end": 10, "text": "second segment"},
            {"start": 10, "end": 15, "text": "third segment"},
        ]
        scored = _score_visual_necessity(segments)
        assert len(scored) == 3

    def test_scores_are_bounded_zero_to_one(self):
        segments = [
            {
                "start": 0,
                "end": 5,
                "text": "As you can see click the button on the top right of the dashboard chart navigate to settings and expand the menu here",
            },
        ]
        scored = _score_visual_necessity(segments)
        for _, score, _ in scored:
            assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Clear mode
# ---------------------------------------------------------------------------


class TestClearMode:
    """Tests for clear mode (removing frames and metadata)."""

    def test_clear_only_returns_cleared_result(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00")
            tmp = f.name
        try:
            with (
                mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"),
                mock.patch("augent.mcp._get_obsidian_vault", return_value=None),
            ):
                result = handle_visual({"video_path": tmp, "clear": True})
                assert result["cleared"] is True
                assert "removed_frames" in result
                assert "removed_md" in result
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# URL download path
# ---------------------------------------------------------------------------


class TestURLDownload:
    """Tests for the URL-to-video download path."""

    def test_url_download_failure_raises(self):
        with (
            mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"),
            mock.patch(
                "subprocess.run",
                return_value=mock.Mock(
                    returncode=1, stdout="", stderr="download failed"
                ),
            ),
        ):
            with pytest.raises(RuntimeError, match="Video download failed"):
                handle_visual(
                    {
                        "url": "https://youtube.com/watch?v=bad",
                        "query": "test",
                    }
                )

    def test_missing_ytdlp_raises(self):
        with mock.patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="yt-dlp not found"):
                handle_visual(
                    {
                        "url": "https://youtube.com/watch?v=test",
                        "query": "test",
                    }
                )
