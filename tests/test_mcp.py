"""
Tests for the MCP server protocol layer.

Tests JSON-RPC routing, tool listing, response formatting,
and handlers that don't require audio processing (list_files,
memory ops, error cases).
"""

import json
import os
import tempfile
from io import StringIO
from unittest import mock

import pytest

from augent.mcp import (
    _get_style_instruction,
    handle_clear_memory,
    handle_initialize,
    handle_list_files,
    handle_list_memories,
    handle_memory_stats,
    handle_request,
    handle_search_memory,
    handle_tools_call,
    handle_tools_list,
    send_error,
    send_response,
)

# --- Helpers ---


def capture_stdout(func, *args, **kwargs):
    """Call func and return the parsed JSON written to stdout."""
    buf = StringIO()
    with mock.patch("sys.stdout", buf):
        func(*args, **kwargs)
    return json.loads(buf.getvalue().strip())


# --- JSON-RPC response formatting ---


class TestSendResponse:
    def test_sends_valid_json(self):
        resp = capture_stdout(send_response, {"jsonrpc": "2.0", "id": 1, "result": {}})
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1

    def test_sends_error(self):
        resp = capture_stdout(send_error, 1, -32600, "Bad request")
        assert resp["error"]["code"] == -32600
        assert resp["error"]["message"] == "Bad request"


# --- Initialize ---


class TestInitialize:
    def test_returns_protocol_version(self):
        resp = capture_stdout(handle_initialize, 1, {})
        result = resp["result"]
        assert "protocolVersion" in result
        assert result["serverInfo"]["name"] == "augent"
        assert result["serverInfo"]["version"] == "2026.3.29"

    def test_declares_tools_capability(self):
        resp = capture_stdout(handle_initialize, 1, {})
        assert "tools" in resp["result"]["capabilities"]


# --- Tools list ---


class TestToolsList:
    def test_returns_22_tools(self):
        resp = capture_stdout(handle_tools_list, 1)
        tools = resp["result"]["tools"]
        assert len(tools) == 22

    def test_all_tools_have_required_fields(self):
        resp = capture_stdout(handle_tools_list, 1)
        for tool in resp["result"]["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

    def test_expected_tool_names(self):
        resp = capture_stdout(handle_tools_list, 1)
        names = {t["name"] for t in resp["result"]["tools"]}
        expected = {
            "download_audio",
            "transcribe_audio",
            "search_audio",
            "deep_search",
            "take_notes",
            "chapters",
            "batch_search",
            "text_to_speech",
            "search_proximity",
            "identify_speakers",
            "list_files",
            "list_memories",
            "memory_stats",
            "clear_memory",
            "search_memory",
            "separate_audio",
            "clip_export",
            "highlights",
            "tag",
            "rebuild_graph",
            "visual",
            "spaces",
        }
        assert names == expected

    def test_disabled_tools_filtered(self):
        """Config disabled_tools should hide tools from the list."""
        import augent.config as config_mod

        original = config_mod._config
        try:
            config_mod._config = dict(config_mod.DEFAULTS)
            config_mod._config["disabled_tools"] = ["tag", "clear_memory"]
            resp = capture_stdout(handle_tools_list, 1)
            names = {t["name"] for t in resp["result"]["tools"]}
            assert "tag" not in names
            assert "clear_memory" not in names
            assert len(resp["result"]["tools"]) == 20
        finally:
            config_mod._config = original

    def test_disabled_tool_call_blocked(self):
        """Calling a disabled tool should return an error."""
        import augent.config as config_mod

        original = config_mod._config
        try:
            config_mod._config = dict(config_mod.DEFAULTS)
            config_mod._config["disabled_tools"] = ["clear_memory"]
            resp = capture_stdout(
                handle_tools_call,
                1,
                {"name": "clear_memory", "arguments": {}},
            )
            assert resp["error"]["code"] == -32602
            assert "disabled" in resp["error"]["message"]
        finally:
            config_mod._config = original


# --- Request routing ---


class TestRequestRouting:
    def test_initialize_routes(self):
        resp = capture_stdout(
            handle_request,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert "result" in resp

    def test_tools_list_routes(self):
        resp = capture_stdout(
            handle_request, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        assert "tools" in resp["result"]

    def test_unknown_method_returns_error(self):
        resp = capture_stdout(
            handle_request, {"jsonrpc": "2.0", "id": 3, "method": "nonexistent/method"}
        )
        assert resp["error"]["code"] == -32601

    def test_notification_no_response(self):
        """Notifications (no id) should not produce output."""
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            handle_request({"method": "notifications/initialized"})
        assert buf.getvalue() == ""

    def test_unknown_tool_returns_error(self):
        resp = capture_stdout(
            handle_tools_call, 1, {"name": "nonexistent_tool", "arguments": {}}
        )
        assert resp["error"]["code"] == -32602


# --- list_files handler ---


class TestListFiles:
    def test_lists_audio_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some fake files
            for name in ["a.mp3", "b.wav", "c.txt", "d.m4a"]:
                open(os.path.join(tmpdir, name), "w").close()

            result = handle_list_files({"directory": tmpdir})
            assert result["count"] == 3  # mp3, wav, m4a
            names = {f["name"] for f in result["files"]}
            assert "a.mp3" in names
            assert "b.wav" in names
            assert "d.m4a" in names
            assert "c.txt" not in names

    def test_custom_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "notes.txt"), "w").close()
            open(os.path.join(tmpdir, "audio.mp3"), "w").close()

            result = handle_list_files({"directory": tmpdir, "pattern": "*.txt"})
            assert result["count"] == 1
            assert result["files"][0]["name"] == "notes.txt"

    def test_recursive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "sub")
            os.makedirs(subdir)
            open(os.path.join(tmpdir, "top.mp3"), "w").close()
            open(os.path.join(subdir, "deep.mp3"), "w").close()

            result_flat = handle_list_files({"directory": tmpdir})
            assert result_flat["count"] == 1

            result_deep = handle_list_files({"directory": tmpdir, "recursive": True})
            assert result_deep["count"] == 2

    def test_missing_directory_raises(self):
        with pytest.raises(ValueError, match="Missing required"):
            handle_list_files({})

    def test_nonexistent_directory_raises(self):
        with pytest.raises(ValueError, match="Directory not found"):
            handle_list_files({"directory": "/nonexistent/path"})

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_list_files({"directory": tmpdir})
            assert result["count"] == 0
            assert result["files"] == []


# --- Memory handlers ---


class TestMemoryHandlers:
    def test_memory_stats_returns_dict(self):
        with tempfile.TemporaryDirectory():
            with mock.patch("augent.mcp.get_memory_stats") as mock_stats:
                mock_stats.return_value = {
                    "entries": 0,
                    "total_audio_duration_hours": 0,
                    "memory_size_mb": 0,
                }
                result = handle_memory_stats({})
                assert "entries" in result

    def test_clear_memory_returns_count(self):
        with mock.patch("augent.mcp.clear_memory") as mock_clear:
            mock_clear.return_value = 5
            result = handle_clear_memory({})
            assert result["cleared"] == 5
            assert "5" in result["message"]

    def test_list_memories_returns_list(self):
        with mock.patch("augent.mcp.list_memories") as mock_list:
            mock_list.return_value = [
                {"title": "test", "duration": 60, "date": "2026-02-16"}
            ]
            result = handle_list_memories({})
            assert result["count"] == 1
            assert result["transcriptions"][0]["title"] == "test"


# --- Style instructions ---


class TestStyleInstructions:
    @pytest.mark.parametrize(
        "style", ["tldr", "notes", "highlight", "eye-candy", "quiz"]
    )
    def test_all_styles_return_instructions(self, style):
        instruction = _get_style_instruction(style)
        assert isinstance(instruction, str)
        assert len(instruction) > 50

    def test_unknown_style_falls_back_to_notes(self):
        instruction = _get_style_instruction("nonexistent")
        notes = _get_style_instruction("notes")
        assert instruction == notes

    def test_quiz_instruction_mentions_answer_key(self):
        instruction = _get_style_instruction("quiz")
        assert "Answer Key" in instruction

    def test_save_instruction_present(self):
        instruction = _get_style_instruction("notes")
        assert "save_content" in instruction


# --- Tool call error handling ---


class TestToolCallErrors:
    def test_missing_audio_path_search(self):
        resp = capture_stdout(
            handle_tools_call,
            1,
            {"name": "search_audio", "arguments": {"keywords": ["test"]}},
        )
        assert resp["error"]["code"] == -32602

    def test_missing_keywords_search(self):
        resp = capture_stdout(
            handle_tools_call,
            1,
            {"name": "search_audio", "arguments": {"audio_path": "/fake.mp3"}},
        )
        assert resp["error"]["code"] == -32602

    def test_missing_url_take_notes(self):
        resp = capture_stdout(
            handle_tools_call, 1, {"name": "take_notes", "arguments": {}}
        )
        assert resp["error"]["code"] == -32602

    def test_missing_query_search_memory(self):
        resp = capture_stdout(
            handle_tools_call, 1, {"name": "search_memory", "arguments": {}}
        )
        assert resp["error"]["code"] == -32602

    def test_missing_audio_path_proximity(self):
        resp = capture_stdout(
            handle_tools_call,
            1,
            {
                "name": "search_proximity",
                "arguments": {"keyword1": "a", "keyword2": "b"},
            },
        )
        assert resp["error"]["code"] == -32602


# --- search_memory ---


class TestSearchMemory:
    def test_missing_query_raises(self):
        with pytest.raises(ValueError, match="Missing required parameter: query"):
            handle_search_memory({})

    def test_tool_schema_present(self):
        resp = capture_stdout(handle_tools_list, 1)
        tools = resp["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "search_memory" in names
        schema = next(t for t in tools if t["name"] == "search_memory")
        assert "query" in schema["inputSchema"]["properties"]
        assert "query" in schema["inputSchema"]["required"]
        assert "mode" in schema["inputSchema"]["properties"]
        assert schema["inputSchema"]["properties"]["mode"]["enum"] == [
            "keyword",
            "semantic",
        ]
        assert "output" in schema["inputSchema"]["properties"]

    def test_routes_correctly(self):
        with mock.patch("augent.mcp.handle_search_memory") as mock_handler:
            mock_handler.return_value = {
                "query": "test",
                "mode": "keyword",
                "results": [],
                "match_count": 0,
                "total_segments": 0,
                "files_searched": 0,
            }
            resp = capture_stdout(
                handle_tools_call,
                1,
                {"name": "search_memory", "arguments": {"query": "test"}},
            )
            mock_handler.assert_called_once_with({"query": "test"})
            assert "result" in resp

    def test_defaults_to_keyword_mode(self):
        with mock.patch("augent.embeddings.search_memory") as mock_fn:
            mock_fn.return_value = {
                "query": "dog",
                "mode": "keyword",
                "results": [],
                "match_count": 0,
                "total_segments": 0,
                "files_searched": 0,
            }
            handle_search_memory({"query": "dog"})
            mock_fn.assert_called_once_with(
                "dog", top_k=10, mode="keyword", output=None
            )

    def test_semantic_mode_passed(self):
        with mock.patch("augent.embeddings.search_memory") as mock_fn:
            mock_fn.return_value = {
                "query": "test",
                "mode": "semantic",
                "results": [],
                "total_segments": 0,
                "files_searched": 0,
                "model_used": "all-MiniLM-L6-v2",
            }
            handle_search_memory({"query": "test", "mode": "semantic"})
            mock_fn.assert_called_once_with(
                "test",
                top_k=10,
                mode="semantic",
                output=None,
                context_words=25,
                dedup_seconds=0,
            )

    def test_output_param_passed(self):
        with mock.patch("augent.embeddings.search_memory") as mock_fn:
            mock_fn.return_value = {
                "query": "test",
                "mode": "keyword",
                "results": [],
                "match_count": 0,
                "total_segments": 0,
                "files_searched": 0,
            }
            handle_search_memory({"query": "test", "output": "~/Desktop/results.csv"})
            mock_fn.assert_called_once_with(
                "test", top_k=10, mode="keyword", output="~/Desktop/results.csv"
            )


class TestWriteResultsCsv:
    def test_writes_csv_with_title_column(self):
        from augent.embeddings import _write_results_csv

        results = [
            {
                "title": "Episode 1",
                "timestamp": "1:30",
                "text": "...hello **world**...",
                "start": 90,
            },
            {
                "title": "Episode 2",
                "timestamp": "5:00",
                "text": "...foo bar...",
                "start": 300,
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "out.csv")
            written = _write_results_csv(results, path, "test")
            assert os.path.exists(written)
            with open(written) as f:
                content = f.read()
            assert "Source,Timestamp,Snippet" in content
            assert "Episode 1" in content
            assert "hello world" in content  # bold markers stripped
            assert "**" not in content

    def test_writes_csv_with_similarity(self):
        from augent.embeddings import _write_results_csv

        results = [
            {"title": "Ep1", "timestamp": "0:10", "text": "test", "similarity": 0.85},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "out.csv")
            _write_results_csv(results, path, "q")
            with open(path) as f:
                content = f.read()
            assert "Similarity" in content
            assert "0.85" in content

    def test_no_csv_on_empty_results(self):
        """search_memory should not write CSV when results are empty."""
        with mock.patch("augent.embeddings.get_transcription_memory") as mock_mem:
            mock_mem.return_value.get_all_with_segments.return_value = []
            from augent.embeddings import search_memory

            result = search_memory("test", output="/tmp/should_not_exist.csv")
            assert "csv_path" not in result
