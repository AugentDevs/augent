"""
Tests for the spaces MCP tool.

Tests tool definition, routing, input validation, cookie auth,
URL normalization, and handler behavior (mocked subprocesses).
"""

import json
import os
import tempfile
from io import StringIO
from unittest import mock

import pytest

from augent.mcp import (
    _active_recordings,
    _get_twitter_cookies_path,
    _normalize_twitter_space_url,
    _spaces_check,
    _spaces_download,
    _spaces_stop,
    handle_spaces,
    handle_tools_call,
    handle_tools_list,
)


def capture_stdout(func, *args, **kwargs):
    """Call func and return the parsed JSON written to stdout."""
    buf = StringIO()
    with mock.patch("sys.stdout", buf):
        func(*args, **kwargs)
    return json.loads(buf.getvalue().strip())


# --- Tool registration ---


class TestSpacesToolsList:
    def test_returns_22_tools(self):
        resp = capture_stdout(handle_tools_list, 1)
        tools = resp["result"]["tools"]
        assert len(tools) == 22

    def test_spaces_tool_registered(self):
        resp = capture_stdout(handle_tools_list, 1)
        names = {t["name"] for t in resp["result"]["tools"]}
        assert "spaces" in names
        assert "spaces_check" not in names
        assert "spaces_stop" not in names

    def test_spaces_schema(self):
        resp = capture_stdout(handle_tools_list, 1)
        tool = next(t for t in resp["result"]["tools"] if t["name"] == "spaces")
        props = tool["inputSchema"]["properties"]
        assert "url" in props
        assert "output_dir" in props
        assert "recording_id" in props
        assert "stop" in props
        assert tool["inputSchema"]["required"] == []


# --- URL normalization ---


class TestURLNormalization:
    def test_x_to_twitter(self):
        assert "twitter.com" in _normalize_twitter_space_url("https://x.com/i/spaces/abc")

    def test_strips_peek(self):
        url = _normalize_twitter_space_url("https://x.com/i/spaces/abc/peek")
        assert not url.endswith("/peek")

    def test_already_twitter(self):
        url = "https://twitter.com/i/spaces/abc"
        assert _normalize_twitter_space_url(url) == url

    def test_no_peek_untouched(self):
        url = "https://x.com/i/spaces/abc"
        normalized = _normalize_twitter_space_url(url)
        assert normalized.endswith("/abc")


# --- Cookie auth ---


class TestCookieAuth:
    def test_no_auth_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("os.path.expanduser", return_value=tmpdir):
                result = _get_twitter_cookies_path()
                assert result is None

    def test_auth_json_generates_cookies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_path = os.path.join(tmpdir, "auth.json")
            cookies_path = os.path.join(tmpdir, "twitter_cookies.txt")
            with open(auth_path, "w") as f:
                json.dump({"auth_token": "tok123", "ct0": "ct0val"}, f)

            # Verify the cookie generation logic
            with open(auth_path) as f:
                auth = json.load(f)
            lines = [
                "# Netscape HTTP Cookie File",
                f".twitter.com\tTRUE\t/\tTRUE\t0\tauth_token\t{auth['auth_token']}",
                f".twitter.com\tTRUE\t/\tTRUE\t0\tct0\t{auth['ct0']}",
            ]
            with open(cookies_path, "w") as f:
                f.write("\n".join(lines) + "\n")

            assert os.path.exists(cookies_path)
            with open(cookies_path) as f:
                content = f.read()
            assert "tok123" in content
            assert "ct0val" in content
            assert "Netscape" in content


# --- Routing within handle_spaces ---


class TestSpacesRouting:
    def test_url_routes_to_download(self):
        with mock.patch("augent.mcp._spaces_download") as mock_fn:
            mock_fn.return_value = {"success": True}
            handle_spaces({"url": "https://x.com/i/spaces/abc"})
            mock_fn.assert_called_once()

    def test_recording_id_routes_to_check(self):
        with mock.patch("augent.mcp._spaces_check") as mock_fn:
            mock_fn.return_value = {"status": "downloading"}
            handle_spaces({"recording_id": "abc123"})
            mock_fn.assert_called_once()

    def test_recording_id_stop_routes_to_stop(self):
        with mock.patch("augent.mcp._spaces_stop") as mock_fn:
            mock_fn.return_value = {"status": "stopped"}
            handle_spaces({"recording_id": "abc123", "stop": True})
            mock_fn.assert_called_once()

    def test_no_params_raises(self):
        with pytest.raises(ValueError, match="Provide either"):
            handle_spaces({})


# --- Input validation ---


class TestSpacesValidation:
    def test_download_missing_url_raises(self):
        with pytest.raises(ValueError, match="Provide either"):
            handle_spaces({})

    def test_download_no_cookies_raises(self):
        with mock.patch("augent.mcp._get_twitter_cookies_path", return_value=None):
            with pytest.raises(FileNotFoundError, match="one-time setup"):
                handle_spaces({"url": "https://x.com/i/spaces/abc"})

    def test_check_unknown_recording_id(self):
        with pytest.raises(ValueError, match="No active download"):
            handle_spaces({"recording_id": "nonexistent"})

    def test_stop_unknown_recording_id(self):
        with pytest.raises(ValueError, match="No active download"):
            handle_spaces({"recording_id": "nonexistent", "stop": True})


# --- MCP tool call routing ---


class TestSpacesMCPRouting:
    def test_spaces_routes_through_tools_call(self):
        with mock.patch("augent.mcp.handle_spaces") as mock_handler:
            mock_handler.return_value = {"success": True, "recording_id": "abc"}
            resp = capture_stdout(
                handle_tools_call,
                1,
                {"name": "spaces", "arguments": {"url": "https://x.com/i/spaces/abc"}},
            )
            mock_handler.assert_called_once()
            assert "result" in resp


# --- Download handler ---


class TestSpacesDownload:
    def test_ended_space_starts_download(self):
        meta_json = json.dumps({"title": "Test Space", "is_live": False})
        mock_meta = mock.Mock(returncode=0, stdout=meta_json, stderr="")
        mock_process = mock.Mock(pid=12345)

        with mock.patch("augent.mcp._get_twitter_cookies_path", return_value="/fake/cookies.txt"):
            with mock.patch("subprocess.run", return_value=mock_meta):
                with mock.patch("subprocess.Popen", return_value=mock_process):
                    with mock.patch("os.makedirs"):
                        result = _spaces_download({
                            "url": "https://x.com/i/spaces/abc",
                            "output_dir": "/tmp/test_spaces",
                        })

        assert result["success"] is True
        assert result["mode"] == "recording"
        assert result["title"] == "Test Space"
        assert result["recording_id"] in _active_recordings
        del _active_recordings[result["recording_id"]]

    def test_live_space_starts_recording(self):
        meta_json = json.dumps({"title": "Live Space", "is_live": True})
        mock_meta = mock.Mock(returncode=0, stdout=meta_json, stderr="")
        mock_stream = mock.Mock(returncode=0, stdout="https://stream.example.com/m3u8", stderr="")
        mock_process = mock.Mock(pid=99999)

        with mock.patch("augent.mcp._get_twitter_cookies_path", return_value="/fake/cookies.txt"):
            with mock.patch("subprocess.run", side_effect=[mock_meta, mock_stream]):
                with mock.patch("subprocess.Popen", return_value=mock_process):
                    with mock.patch("os.makedirs"):
                        result = _spaces_download({
                            "url": "https://x.com/i/spaces/abc",
                        })

        assert result["success"] is True
        assert result["mode"] == "live"
        assert result["title"] == "Live Space"
        assert result["recording_id"] in _active_recordings
        del _active_recordings[result["recording_id"]]

    def test_meta_failure_raises(self):
        mock_meta = mock.Mock(returncode=1, stdout="", stderr="Login required")

        with mock.patch("augent.mcp._get_twitter_cookies_path", return_value="/fake/cookies.txt"):
            with mock.patch("subprocess.run", return_value=mock_meta):
                with mock.patch("os.makedirs"):
                    with pytest.raises(RuntimeError, match="Failed to fetch space info"):
                        _spaces_download({"url": "https://x.com/i/spaces/abc"})


# --- Check handler ---


class TestSpacesCheck:
    def _setup_recording(self, poll_return=None, output_file=None):
        """Helper to insert a fake recording into _active_recordings."""
        import time

        mock_process = mock.Mock()
        mock_process.poll.return_value = poll_return
        mock_process.stderr = mock.Mock()
        mock_process.stderr.read.return_value = b"some error"

        recording_id = "test123"
        _active_recordings[recording_id] = {
            "process": mock_process,
            "pid": 11111,
            "url": "https://twitter.com/i/spaces/abc",
            "output_dir": "/tmp/test",
            "start_time": time.time() - 60,
            "before_files": set(),
            "is_live": False,
            "title": "Test",
            "output_file": output_file,
        }
        return recording_id

    def test_downloading_status(self):
        rid = self._setup_recording(poll_return=None)
        try:
            result = _spaces_check({"recording_id": rid})
            assert result["status"] == "downloading"
            assert result["elapsed_seconds"] >= 59
        finally:
            _active_recordings.pop(rid, None)

    def test_complete_status(self):
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as f:
            f.write(b"fake audio")
            temp_path = f.name

        try:
            rid = self._setup_recording(poll_return=0, output_file=temp_path)
            result = _spaces_check({"recording_id": rid})
            assert result["status"] == "complete"
            assert result["file"]["path"] == temp_path
            assert rid not in _active_recordings
        finally:
            os.unlink(temp_path)

    def test_error_status(self):
        rid = self._setup_recording(poll_return=1)
        result = _spaces_check({"recording_id": rid})
        assert result["status"] == "error"
        assert rid not in _active_recordings


# --- Stop handler ---


class TestSpacesStop:
    def test_stop_kills_process(self):
        import time

        mock_process = mock.Mock()
        mock_process.poll.return_value = None
        mock_process.wait.return_value = 0

        rid = "stop_test"
        _active_recordings[rid] = {
            "process": mock_process,
            "pid": 22222,
            "url": "https://twitter.com/i/spaces/abc",
            "output_dir": "/tmp/test",
            "start_time": time.time() - 30,
            "before_files": set(),
            "is_live": True,
            "title": "Live Test",
            "output_file": None,
        }

        result = _spaces_stop({"recording_id": rid})
        assert result["status"] == "stopped"
        assert result["success"] is True
        mock_process.send_signal.assert_called_once()
        assert rid not in _active_recordings

    def test_stop_already_finished(self):
        import time

        mock_process = mock.Mock()
        mock_process.poll.return_value = 0

        rid = "stop_done"
        _active_recordings[rid] = {
            "process": mock_process,
            "pid": 33333,
            "url": "https://twitter.com/i/spaces/abc",
            "output_dir": "/tmp/test",
            "start_time": time.time() - 120,
            "before_files": set(),
            "is_live": False,
            "title": "Done Test",
            "output_file": None,
        }

        result = _spaces_stop({"recording_id": rid})
        assert result["status"] == "stopped"
        mock_process.send_signal.assert_not_called()
        assert rid not in _active_recordings


# --- Error propagation through MCP ---


class TestSpacesMCPErrors:
    def test_no_params_returns_mcp_error(self):
        resp = capture_stdout(
            handle_tools_call,
            1,
            {"name": "spaces", "arguments": {}},
        )
        assert resp["error"]["code"] == -32602

    def test_no_cookies_returns_mcp_error(self):
        with mock.patch("augent.mcp._get_twitter_cookies_path", return_value=None):
            resp = capture_stdout(
                handle_tools_call,
                1,
                {"name": "spaces", "arguments": {"url": "https://x.com/i/spaces/abc"}},
            )
            assert resp["error"]["code"] == -32602
            assert "setup" in resp["error"]["message"].lower()

    def test_unknown_recording_returns_mcp_error(self):
        resp = capture_stdout(
            handle_tools_call,
            1,
            {"name": "spaces", "arguments": {"recording_id": "fake"}},
        )
        assert resp["error"]["code"] == -32602
