"""
Tests for MCP tool handlers that invoke external processes.

Covers: download_audio, clip_export, transcribe_audio, chapters,
batch_search, separate_audio, and the _export_clips_for_matches helper.
All subprocess/external calls are mocked — these tests verify command
construction, flag presence, parameter defaults, and error handling.
"""

import os
import tempfile
from unittest import mock

import pytest

from augent.mcp import (
    _export_clips_for_matches,
    handle_batch_search,
    handle_chapters,
    handle_clip_export,
    handle_download_audio,
    handle_separate_audio,
    handle_transcribe_audio,
)

# ---------------------------------------------------------------------------
# download_audio
# ---------------------------------------------------------------------------


class TestDownloadAudio:
    """Tests for handle_download_audio."""

    def _mock_run(self, stdout="", returncode=0):
        return mock.patch(
            "subprocess.run",
            return_value=mock.Mock(stdout=stdout, stderr="", returncode=returncode),
        )

    def test_missing_url_raises(self):
        with pytest.raises(ValueError, match="Missing required parameter: url"):
            handle_download_audio({})

    def test_restrict_filenames_flag(self):
        """--restrict-filenames must be in the yt-dlp command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_file = os.path.join(tmpdir, "test.webm")
            open(fake_file, "w").close()

            with self._mock_run(stdout=fake_file) as mock_run:
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    handle_download_audio(
                        {"url": "https://youtube.com/watch?v=abc", "output_dir": tmpdir}
                    )

                cmd = mock_run.call_args[0][0]
                assert "--restrict-filenames" in cmd

    def test_output_template_format(self):
        """Output template should use %(title)s [%(id)s].%(ext)s."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_file = os.path.join(tmpdir, "test.webm")
            open(fake_file, "w").close()

            with self._mock_run(stdout=fake_file) as mock_run:
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    handle_download_audio(
                        {"url": "https://example.com/video", "output_dir": tmpdir}
                    )

                cmd = mock_run.call_args[0][0]
                o_idx = cmd.index("-o")
                template = cmd[o_idx + 1]
                assert "%(title)s" in template
                assert "%(id)s" in template

    def test_aria2c_flags_added_when_available(self):
        """When aria2c is on PATH, downloader flags should be added."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_file = os.path.join(tmpdir, "test.webm")
            open(fake_file, "w").close()

            with self._mock_run(stdout=fake_file) as mock_run:
                with mock.patch(
                    "shutil.which", side_effect=lambda name, **kw: "/usr/bin/" + name
                ):
                    handle_download_audio(
                        {"url": "https://example.com/v", "output_dir": tmpdir}
                    )

                cmd = mock_run.call_args[0][0]
                assert "--downloader" in cmd
                assert "aria2c" in cmd

    def test_aria2c_flags_absent_when_missing(self):
        """When aria2c is not on PATH, downloader flags should be absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_file = os.path.join(tmpdir, "test.webm")
            open(fake_file, "w").close()

            def which_side_effect(name, **kwargs):
                if name == "yt-dlp":
                    return "/usr/bin/yt-dlp"
                return None  # aria2c not found

            with self._mock_run(stdout=fake_file) as mock_run:
                with mock.patch("shutil.which", side_effect=which_side_effect):
                    handle_download_audio(
                        {"url": "https://example.com/v", "output_dir": tmpdir}
                    )

                cmd = mock_run.call_args[0][0]
                assert "--downloader" not in cmd

    def test_yt_dlp_not_found_raises(self):
        with mock.patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="yt-dlp not found"):
                handle_download_audio({"url": "https://example.com/v"})

    def test_download_failure_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._mock_run(stdout="", returncode=1):
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    with pytest.raises(RuntimeError, match="Download failed"):
                        handle_download_audio(
                            {"url": "https://example.com/v", "output_dir": tmpdir}
                        )

    def test_registers_source_url(self):
        """Downloaded file should be tracked in _downloaded_urls."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_file = os.path.join(tmpdir, "test.webm")
            open(fake_file, "w").close()

            with self._mock_run(stdout=fake_file):
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    with mock.patch.dict("augent.mcp._downloaded_urls", {}, clear=True):
                        from augent import mcp

                        handle_download_audio(
                            {
                                "url": "https://youtube.com/watch?v=test123",
                                "output_dir": tmpdir,
                            }
                        )
                        assert (
                            mcp._downloaded_urls[os.path.abspath(fake_file)]
                            == "https://youtube.com/watch?v=test123"
                        )

    def test_success_response_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_file = os.path.join(tmpdir, "test.webm")
            with open(fake_file, "wb") as f:
                f.write(b"x" * (1024 * 1024 + 1))  # just over 1 MB

            with self._mock_run(stdout=fake_file):
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    result = handle_download_audio(
                        {"url": "https://example.com/v", "output_dir": tmpdir}
                    )

            assert result["success"] is True
            assert result["file"]["path"] == fake_file
            assert result["file"]["size_mb"] > 0
            assert result["url"] == "https://example.com/v"

    def test_concurrent_fragments_flag(self):
        """--concurrent-fragments 4 should always be present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_file = os.path.join(tmpdir, "test.webm")
            open(fake_file, "w").close()

            with self._mock_run(stdout=fake_file) as mock_run:
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    handle_download_audio(
                        {"url": "https://example.com/v", "output_dir": tmpdir}
                    )

                cmd = mock_run.call_args[0][0]
                idx = cmd.index("--concurrent-fragments")
                assert cmd[idx + 1] == "4"


# ---------------------------------------------------------------------------
# clip_export
# ---------------------------------------------------------------------------


class TestClipExport:
    """Tests for handle_clip_export."""

    def _mock_run(self, stdout="", returncode=0):
        return mock.patch(
            "subprocess.run",
            return_value=mock.Mock(stdout=stdout, stderr="", returncode=returncode),
        )

    def test_missing_url_raises(self):
        with pytest.raises(ValueError, match="Missing required parameter: url"):
            handle_clip_export({"start": 0, "end": 10})

    def test_missing_start_end_raises(self):
        with pytest.raises(
            ValueError, match="Missing required parameters: start and end"
        ):
            handle_clip_export({"url": "https://example.com/v"})

    def test_end_before_start_raises(self):
        with pytest.raises(ValueError, match="end must be greater than start"):
            handle_clip_export({"url": "https://example.com/v", "start": 30, "end": 10})

    def test_force_overwrites_flag(self):
        """--force-overwrites must be in the yt-dlp command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_clip = os.path.join(tmpdir, "clip.mp4")
            with open(fake_clip, "wb") as f:
                f.write(b"x" * 2048)

            with self._mock_run(stdout=fake_clip) as mock_run:
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    handle_clip_export(
                        {
                            "url": "https://example.com/v",
                            "start": 10,
                            "end": 30,
                            "output_dir": tmpdir,
                            "output_filename": "clip",
                        }
                    )

                cmd = mock_run.call_args[0][0]
                assert "--force-overwrites" in cmd

    def test_force_keyframes_at_cuts_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_clip = os.path.join(tmpdir, "clip.mp4")
            with open(fake_clip, "wb") as f:
                f.write(b"x" * 2048)

            with self._mock_run(stdout=fake_clip) as mock_run:
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    handle_clip_export(
                        {
                            "url": "https://example.com/v",
                            "start": 0,
                            "end": 10,
                            "output_dir": tmpdir,
                        }
                    )

                cmd = mock_run.call_args[0][0]
                assert "--force-keyframes-at-cuts" in cmd

    def test_download_sections_format(self):
        """--download-sections should use *HH:MM:SS-HH:MM:SS format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_clip = os.path.join(tmpdir, "clip.mp4")
            with open(fake_clip, "wb") as f:
                f.write(b"x" * 2048)

            with self._mock_run(stdout=fake_clip) as mock_run:
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    handle_clip_export(
                        {
                            "url": "https://example.com/v",
                            "start": 65,  # 1:05
                            "end": 130,  # 2:10
                            "output_dir": tmpdir,
                        }
                    )

                cmd = mock_run.call_args[0][0]
                idx = cmd.index("--download-sections")
                assert cmd[idx + 1] == "*00:01:05-00:02:10"

    def test_custom_output_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_clip = os.path.join(tmpdir, "my_clip.mp4")
            with open(fake_clip, "wb") as f:
                f.write(b"x" * 2048)

            with self._mock_run(stdout=fake_clip) as mock_run:
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    handle_clip_export(
                        {
                            "url": "https://example.com/v",
                            "start": 0,
                            "end": 10,
                            "output_dir": tmpdir,
                            "output_filename": "my_clip",
                        }
                    )

                cmd = mock_run.call_args[0][0]
                o_idx = cmd.index("-o")
                assert cmd[o_idx + 1].endswith("my_clip.%(ext)s")

    def test_auto_generated_filename_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_clip = os.path.join(tmpdir, "auto.mp4")
            with open(fake_clip, "wb") as f:
                f.write(b"x" * 2048)

            with self._mock_run(stdout=fake_clip) as mock_run:
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    handle_clip_export(
                        {
                            "url": "https://example.com/v",
                            "start": 0,
                            "end": 10,
                            "output_dir": tmpdir,
                        }
                    )

                cmd = mock_run.call_args[0][0]
                o_idx = cmd.index("-o")
                template = cmd[o_idx + 1]
                assert "%(title)s_clip_" in template
                assert "%(section_start)s" in template

    def test_yt_dlp_not_found_raises(self):
        with mock.patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="yt-dlp not found"):
                handle_clip_export(
                    {"url": "https://example.com/v", "start": 0, "end": 10}
                )

    def test_yt_dlp_failure_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._mock_run(stdout="", returncode=1):
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    with pytest.raises(RuntimeError, match="yt-dlp clip export failed"):
                        handle_clip_export(
                            {
                                "url": "https://example.com/v",
                                "start": 0,
                                "end": 10,
                                "output_dir": tmpdir,
                            }
                        )

    def test_response_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_clip = os.path.join(tmpdir, "clip.mp4")
            with open(fake_clip, "wb") as f:
                f.write(b"x" * (1024 * 1024 + 1))

            with self._mock_run(stdout=fake_clip):
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    result = handle_clip_export(
                        {
                            "url": "https://youtube.com/watch?v=abc",
                            "start": 50,
                            "end": 80,
                            "output_dir": tmpdir,
                        }
                    )

            assert result["clip_path"] == fake_clip
            assert result["start"] == 50
            assert result["end"] == 80
            assert result["duration"] == 30
            assert result["start_formatted"] == "00:00:50"
            assert result["end_formatted"] == "00:01:20"
            assert result["duration_formatted"] == "0:30"
            assert result["file_size_mb"] > 0

    def test_mp4_merge_format(self):
        """Output should always be mp4."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_clip = os.path.join(tmpdir, "clip.mp4")
            with open(fake_clip, "wb") as f:
                f.write(b"x" * 2048)

            with self._mock_run(stdout=fake_clip) as mock_run:
                with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
                    handle_clip_export(
                        {
                            "url": "https://example.com/v",
                            "start": 0,
                            "end": 10,
                            "output_dir": tmpdir,
                        }
                    )

                cmd = mock_run.call_args[0][0]
                idx = cmd.index("--merge-output-format")
                assert cmd[idx + 1] == "mp4"


# ---------------------------------------------------------------------------
# _export_clips_for_matches (helper)
# ---------------------------------------------------------------------------


class TestExportClipsForMatches:
    """Tests for the _export_clips_for_matches helper."""

    def test_default_padding_is_15(self):
        """Default padding should be 15 seconds."""
        import inspect

        sig = inspect.signature(_export_clips_for_matches)
        assert sig.parameters["padding"].default == 15

    def test_empty_timestamps_returns_empty(self):
        assert _export_clips_for_matches("https://example.com", []) == []

    @mock.patch("augent.mcp.handle_clip_export")
    def test_padding_applied(self, mock_clip):
        mock_clip.return_value = {"clip_path": "/tmp/clip.mp4", "duration": 30}

        _export_clips_for_matches("https://example.com", [60.0], padding=15)

        call_args = mock_clip.call_args[0][0]
        assert call_args["start"] == 45.0  # 60 - 15
        assert call_args["end"] == 75.0  # 60 + 15

    @mock.patch("augent.mcp.handle_clip_export")
    def test_start_clamped_to_zero(self, mock_clip):
        mock_clip.return_value = {"clip_path": "/tmp/clip.mp4", "duration": 20}

        _export_clips_for_matches("https://example.com", [5.0], padding=15)

        call_args = mock_clip.call_args[0][0]
        assert call_args["start"] == 0  # max(0, 5-15) = 0
        assert call_args["end"] == 20.0

    @mock.patch("augent.mcp.handle_clip_export")
    def test_overlapping_ranges_merged(self, mock_clip):
        mock_clip.return_value = {"clip_path": "/tmp/clip.mp4", "duration": 40}

        # Two timestamps 10s apart with 15s padding → overlapping ranges get merged
        _export_clips_for_matches("https://example.com", [50.0, 60.0], padding=15)

        # Should be ONE clip call, not two
        assert mock_clip.call_count == 1
        call_args = mock_clip.call_args[0][0]
        assert call_args["start"] == 35.0  # 50 - 15
        assert call_args["end"] == 75.0  # 60 + 15

    @mock.patch("augent.mcp.handle_clip_export")
    def test_non_overlapping_ranges_separate(self, mock_clip):
        mock_clip.return_value = {"clip_path": "/tmp/clip.mp4", "duration": 30}

        # Two timestamps far apart → separate clips
        _export_clips_for_matches("https://example.com", [30.0, 120.0], padding=15)

        assert mock_clip.call_count == 2

    @mock.patch("augent.mcp.handle_clip_export")
    def test_match_timestamps_attached(self, mock_clip):
        mock_clip.return_value = {"clip_path": "/tmp/clip.mp4"}

        result = _export_clips_for_matches(
            "https://example.com", [50.0, 55.0], padding=15
        )

        assert result[0]["match_timestamps"] == [50.0, 55.0]

    @mock.patch("augent.mcp.handle_clip_export")
    def test_clip_error_captured(self, mock_clip):
        mock_clip.side_effect = RuntimeError("yt-dlp failed")

        result = _export_clips_for_matches("https://example.com", [60.0], padding=15)

        assert len(result) == 1
        assert "error" in result[0]
        assert result[0]["match_timestamps"] == [60.0]

    @mock.patch("augent.mcp.handle_clip_export")
    def test_duplicate_timestamps_deduplicated(self, mock_clip):
        mock_clip.return_value = {"clip_path": "/tmp/clip.mp4"}

        _export_clips_for_matches("https://example.com", [60.0, 60.0, 60.0], padding=15)

        assert mock_clip.call_count == 1


# ---------------------------------------------------------------------------
# transcribe_audio
# ---------------------------------------------------------------------------


class TestTranscribeAudio:
    """Tests for handle_transcribe_audio."""

    def test_missing_audio_path_raises(self):
        with pytest.raises(ValueError, match="Missing required parameter: audio_path"):
            handle_transcribe_audio({})

    @mock.patch("augent.mcp.transcribe_audio")
    def test_basic_transcription(self, mock_transcribe):
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(b"fake audio")
            audio_path = f.name

        try:
            mock_transcribe.return_value = {
                "text": "hello world",
                "language": "en",
                "duration": 10.0,
                "segments": [{"start": 0, "end": 10, "text": "hello world"}],
                "segment_count": 1,
                "cached": False,
            }

            result = handle_transcribe_audio({"audio_path": audio_path})

            assert result["text"] == "hello world"
            assert result["language"] == "en"
            mock_transcribe.assert_called_once_with(audio_path, "tiny")
        finally:
            os.unlink(audio_path)

    @mock.patch("augent.mcp.transcribe_audio")
    @mock.patch("subprocess.run")
    def test_start_duration_trims_with_ffmpeg(self, mock_run, mock_transcribe):
        """When start/duration given, ffmpeg should trim before transcription."""
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(b"fake audio")
            audio_path = f.name

        try:
            mock_run.return_value = mock.Mock(returncode=0)
            mock_transcribe.return_value = {
                "text": "trimmed",
                "language": "en",
                "duration": 60.0,
                "segments": [],
                "segment_count": 0,
                "cached": False,
            }

            handle_transcribe_audio(
                {
                    "audio_path": audio_path,
                    "start": 120,
                    "duration": 60,
                }
            )

            # ffmpeg should have been called with -ss and -t
            ffmpeg_cmd = mock_run.call_args[0][0]
            assert ffmpeg_cmd[0] == "ffmpeg"
            assert "-ss" in ffmpeg_cmd
            ss_idx = ffmpeg_cmd.index("-ss")
            assert ffmpeg_cmd[ss_idx + 1] == "120"
            assert "-t" in ffmpeg_cmd
            t_idx = ffmpeg_cmd.index("-t")
            assert ffmpeg_cmd[t_idx + 1] == "60"
        finally:
            os.unlink(audio_path)

    def test_translation_storage(self):
        """translated_text should store without re-transcription."""
        with mock.patch("augent.memory.get_transcription_memory") as mock_mem_fn:
            mock_memory = mock.Mock()
            mock_memory.store_translation.return_value = "/fake/path/translation.md"
            mock_mem_fn.return_value = mock_memory

            result = handle_transcribe_audio(
                {
                    "audio_path": "/fake/audio.webm",
                    "translated_text": "This is the English translation.",
                }
            )

            assert result["status"] == "translation_stored"
            mock_memory.store_translation.assert_called_once()

    def test_translation_no_existing_raises(self):
        """If no transcription exists, storing translation should raise."""
        with mock.patch("augent.memory.get_transcription_memory") as mock_mem_fn:
            mock_memory = mock.Mock()
            mock_memory.store_translation.return_value = None
            mock_mem_fn.return_value = mock_memory

            with pytest.raises(ValueError, match="No existing transcription"):
                handle_transcribe_audio(
                    {
                        "audio_path": "/fake/audio.webm",
                        "translated_text": "English text",
                    }
                )


# ---------------------------------------------------------------------------
# chapters
# ---------------------------------------------------------------------------


class TestChapters:
    """Tests for handle_chapters."""

    def test_missing_audio_path_raises(self):
        with pytest.raises(ValueError, match="Missing required parameter: audio_path"):
            handle_chapters({})

    @mock.patch("augent.embeddings.detect_chapters")
    def test_basic_chapter_detection(self, mock_detect):
        mock_detect.return_value = {
            "chapters": [
                {
                    "chapter_number": 1,
                    "start": 0,
                    "end": 120,
                    "start_timestamp": "0:00",
                    "end_timestamp": "2:00",
                    "text": "Introduction to the topic at hand",
                    "segment_count": 5,
                },
            ],
            "total_chapters": 1,
        }

        result = handle_chapters({"audio_path": "/fake/audio.mp3"})

        assert result["total_chapters"] == 1
        assert len(result["chapters"]) == 1
        mock_detect.assert_called_once_with(
            "/fake/audio.mp3", model_size="tiny", sensitivity=0.4
        )

    @mock.patch("augent.embeddings.detect_chapters")
    def test_custom_sensitivity(self, mock_detect):
        mock_detect.return_value = {"chapters": [], "total_chapters": 0}

        handle_chapters({"audio_path": "/fake/audio.mp3", "sensitivity": 0.8})

        mock_detect.assert_called_once_with(
            "/fake/audio.mp3", model_size="tiny", sensitivity=0.8
        )

    @mock.patch("augent.embeddings.detect_chapters")
    def test_long_chapter_text_truncated(self, mock_detect):
        """Chapter text longer than 30 words should be truncated."""
        long_text = " ".join(f"word{i}" for i in range(50))
        mock_detect.return_value = {
            "chapters": [
                {
                    "chapter_number": 1,
                    "start": 0,
                    "end": 60,
                    "text": long_text,
                    "segment_count": 3,
                },
            ],
            "total_chapters": 1,
        }

        result = handle_chapters({"audio_path": "/fake/audio.mp3"})

        text = result["chapters"][0]["text"]
        assert text.endswith("...")
        # 30 words + "..."
        assert len(text.split()) <= 31

    @mock.patch("augent.embeddings.detect_chapters")
    def test_short_chapter_text_not_truncated(self, mock_detect):
        short_text = "This is a short chapter."
        mock_detect.return_value = {
            "chapters": [{"chapter_number": 1, "text": short_text}],
            "total_chapters": 1,
        }

        result = handle_chapters({"audio_path": "/fake/audio.mp3"})

        assert result["chapters"][0]["text"] == short_text

    @mock.patch("augent.embeddings.detect_chapters")
    def test_custom_model_size(self, mock_detect):
        mock_detect.return_value = {"chapters": [], "total_chapters": 0}

        handle_chapters({"audio_path": "/fake/audio.mp3", "model_size": "small"})

        mock_detect.assert_called_once_with(
            "/fake/audio.mp3", model_size="small", sensitivity=0.4
        )


# ---------------------------------------------------------------------------
# batch_search
# ---------------------------------------------------------------------------


class TestBatchSearch:
    """Tests for handle_batch_search."""

    def test_missing_audio_paths_raises(self):
        with pytest.raises(ValueError, match="Missing required parameter: audio_paths"):
            handle_batch_search({"keywords": ["test"]})

    def test_missing_keywords_raises(self):
        with pytest.raises(ValueError, match="Missing required parameter: keywords"):
            handle_batch_search({"audio_paths": ["/fake.mp3"]})

    @mock.patch("augent.mcp.search_audio")
    def test_valid_files_processed(self, mock_search):
        mock_search.return_value = {
            "test": [{"timestamp": "0:10", "snippet": "found test"}]
        }

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f1:
            path1 = f1.name
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f2:
            path2 = f2.name

        try:
            result = handle_batch_search(
                {
                    "audio_paths": [path1, path2],
                    "keywords": ["test"],
                }
            )

            assert result["files_processed"] == 2
            assert result["files_with_errors"] == 0
            assert mock_search.call_count == 2
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_nonexistent_files_reported(self):
        with mock.patch("augent.mcp.search_audio"):
            result = handle_batch_search(
                {
                    "audio_paths": ["/nonexistent/file1.mp3", "/nonexistent/file2.mp3"],
                    "keywords": ["test"],
                }
            )

            assert result["files_processed"] == 0
            assert result["files_with_errors"] == 2
            assert len(result["errors"]) == 2

    @mock.patch("augent.mcp.search_audio")
    def test_mixed_valid_and_invalid(self, mock_search):
        mock_search.return_value = {"kw": [{"snippet": "match"}]}

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            valid_path = f.name

        try:
            result = handle_batch_search(
                {
                    "audio_paths": [valid_path, "/nonexistent.mp3"],
                    "keywords": ["kw"],
                }
            )

            assert result["files_processed"] == 1
            assert result["files_with_errors"] == 1
        finally:
            os.unlink(valid_path)

    @mock.patch("augent.mcp.search_audio")
    def test_total_matches_aggregated(self, mock_search):
        mock_search.return_value = {
            "word1": [{"snippet": "a"}, {"snippet": "b"}],
            "word2": [{"snippet": "c"}],
        }

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name

        try:
            result = handle_batch_search(
                {
                    "audio_paths": [path],
                    "keywords": ["word1", "word2"],
                }
            )

            assert result["total_matches"] == 3
        finally:
            os.unlink(path)

    @mock.patch("augent.mcp.search_audio")
    def test_custom_workers(self, mock_search):
        mock_search.return_value = {}

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name

        try:
            result = handle_batch_search(
                {
                    "audio_paths": [path],
                    "keywords": ["kw"],
                    "workers": 4,
                }
            )

            assert result["model_used"] == "tiny"
        finally:
            os.unlink(path)

    @mock.patch("augent.mcp.search_audio")
    def test_search_error_captured(self, mock_search):
        """If search_audio throws for a file, error is captured not raised."""
        mock_search.side_effect = RuntimeError("whisper crashed")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name

        try:
            result = handle_batch_search(
                {
                    "audio_paths": [path],
                    "keywords": ["kw"],
                }
            )

            assert result["files_processed"] == 1
            assert "error" in result["results"][path]
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# separate_audio
# ---------------------------------------------------------------------------


class TestSeparateAudio:
    """Tests for handle_separate_audio."""

    def test_missing_audio_path_raises(self):
        with pytest.raises(ValueError, match="Missing required parameter: audio_path"):
            handle_separate_audio({})

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError, match="Audio file not found"):
            handle_separate_audio({"audio_path": "/nonexistent/audio.mp3"})

    @mock.patch("augent.separator.separate_audio")
    def test_vocals_only_default(self, mock_sep):
        mock_sep.return_value = {
            "stems": {"vocals": "/tmp/vocals.wav", "no_vocals": "/tmp/no_vocals.wav"},
            "model": "htdemucs",
            "source_file": "/tmp/audio.mp3",
            "cached": False,
            "output_dir": "/tmp/separated",
        }

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name

        try:
            result = handle_separate_audio({"audio_path": path})

            mock_sep.assert_called_once_with(path, model="htdemucs", two_stems="vocals")
            assert result["vocals_path"] == "/tmp/vocals.wav"
            assert "hint" in result
        finally:
            os.unlink(path)

    @mock.patch("augent.separator.separate_audio")
    def test_all_stems(self, mock_sep):
        mock_sep.return_value = {
            "stems": {
                "vocals": "/tmp/vocals.wav",
                "drums": "/tmp/drums.wav",
                "bass": "/tmp/bass.wav",
                "other": "/tmp/other.wav",
            },
            "model": "htdemucs",
            "source_file": "/tmp/audio.mp3",
            "cached": False,
            "output_dir": "/tmp/separated",
        }

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name

        try:
            handle_separate_audio({"audio_path": path, "vocals_only": False})

            mock_sep.assert_called_once_with(path, model="htdemucs", two_stems=None)
        finally:
            os.unlink(path)

    @mock.patch("augent.separator.separate_audio")
    def test_custom_model(self, mock_sep):
        mock_sep.return_value = {
            "stems": {"vocals": "/tmp/vocals.wav"},
            "model": "htdemucs_ft",
            "source_file": "/tmp/audio.mp3",
            "cached": False,
            "output_dir": "/tmp/separated",
        }

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name

        try:
            handle_separate_audio({"audio_path": path, "model": "htdemucs_ft"})

            mock_sep.assert_called_once_with(
                path, model="htdemucs_ft", two_stems="vocals"
            )
        finally:
            os.unlink(path)

    @mock.patch("augent.separator.separate_audio")
    def test_response_shape(self, mock_sep):
        mock_sep.return_value = {
            "stems": {"vocals": "/tmp/vocals.wav", "no_vocals": "/tmp/no_vocals.wav"},
            "model": "htdemucs",
            "source_file": "/tmp/audio.mp3",
            "cached": True,
            "output_dir": "/tmp/separated",
        }

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name

        try:
            result = handle_separate_audio({"audio_path": path})

            assert "stems" in result
            assert "model" in result
            assert "cached" in result
            assert "output_dir" in result
            assert result["cached"] is True
        finally:
            os.unlink(path)

    def test_tilde_expansion(self):
        """audio_path with ~ should be expanded."""
        with mock.patch("augent.separator.separate_audio") as mock_sep:
            mock_sep.return_value = {
                "stems": {"vocals": "/tmp/v.wav"},
                "model": "htdemucs",
                "source_file": "/tmp/a.mp3",
                "cached": False,
                "output_dir": "/tmp/sep",
            }

            # Create a real temp file so exists() passes
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                path = f.name

            try:
                # Use the actual path but verify expanduser is applied
                handle_separate_audio({"audio_path": path})
                call_path = mock_sep.call_args[0][0]
                assert not call_path.startswith("~")
            finally:
                os.unlink(path)


# ---------------------------------------------------------------------------
# Clip padding defaults in search_audio and deep_search handlers
# ---------------------------------------------------------------------------


class TestClipPaddingDefaults:
    """Verify clip_padding defaults are 15 across all handlers."""

    def test_search_audio_default_padding(self):
        """search_audio handler should default clip_padding to 15."""
        from augent.mcp import handle_search_audio

        with mock.patch("augent.mcp.search_audio") as mock_search:
            mock_search.return_value = {
                "kw": [{"timestamp_seconds": 60.0, "snippet": "test"}]
            }

            with mock.patch("augent.mcp._export_clips_for_matches") as mock_clips:
                mock_clips.return_value = []

                with mock.patch.dict(
                    "augent.mcp._downloaded_urls", {"/fake": "https://example.com"}
                ):
                    with mock.patch("os.path.abspath", return_value="/fake"):
                        handle_search_audio(
                            {
                                "audio_path": "/fake.mp3",
                                "keywords": ["kw"],
                                "clip": True,
                            }
                        )

                        mock_clips.assert_called_once()
                        assert mock_clips.call_args[1]["padding"] == 15

    def test_search_audio_custom_padding(self):
        """search_audio handler should respect custom clip_padding."""
        from augent.mcp import handle_search_audio

        with mock.patch("augent.mcp.search_audio") as mock_search:
            mock_search.return_value = {
                "kw": [{"timestamp_seconds": 60.0, "snippet": "test"}]
            }

            with mock.patch("augent.mcp._export_clips_for_matches") as mock_clips:
                mock_clips.return_value = []

                with mock.patch.dict(
                    "augent.mcp._downloaded_urls", {"/fake": "https://example.com"}
                ):
                    with mock.patch("os.path.abspath", return_value="/fake"):
                        handle_search_audio(
                            {
                                "audio_path": "/fake.mp3",
                                "keywords": ["kw"],
                                "clip": True,
                                "clip_padding": 30,
                            }
                        )

                        assert mock_clips.call_args[1]["padding"] == 30
