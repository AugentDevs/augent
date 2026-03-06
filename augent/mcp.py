"""
Augent MCP Server

Model Context Protocol server for Claude Code integration.
Exposes Augent as a native tool that Claude can call directly.

Tools exposed:
- download_audio: Download audio from video URLs (YouTube, etc.) at maximum speed
- transcribe_audio: Full transcription without keyword search
- search_audio: Search for keywords in audio files
- deep_search: Semantic search by meaning, not just keywords
- take_notes: All-in-one note-taking: download + transcribe + save .txt to Desktop
- chapters: Auto-detect topic chapters in audio
- batch_search: Search multiple audio files in parallel
- text_to_speech: Convert text to natural speech audio using Kokoro TTS
- search_proximity: Find keywords appearing near each other
- identify_speakers: Speaker diarization (who said what)
- list_files: List media files in a directory
- list_memories: List all stored transcriptions
- memory_stats: View transcription memory statistics
- clear_memory: Clear transcription memory
- search_memory: Search across ALL stored transcriptions by meaning

Usage:
  python -m augent.mcp
  # or
  augent-mcp

Add to Claude Code project (.mcp.json):
  {
    "mcpServers": {
      "augent": {
        "command": "augent-mcp"
      }
    }
  }

"""

import json
import os
import sys
from typing import Any

# Check for required dependencies before importing
_MISSING_DEPS = []
try:
    import faster_whisper
except ImportError:
    _MISSING_DEPS.append("faster-whisper")

try:
    import torch
except ImportError:
    _MISSING_DEPS.append("torch")

if _MISSING_DEPS:

    def _dependency_error():
        return {
            "error": f"Missing dependencies: {', '.join(_MISSING_DEPS)}. "
            f"Install with: pip install {' '.join(_MISSING_DEPS)}"
        }

    # Create stub functions that return errors
    def search_audio(*args, **kwargs):
        raise RuntimeError(_dependency_error()["error"])

    def search_audio_full(*args, **kwargs):
        raise RuntimeError(_dependency_error()["error"])

    def transcribe_audio(*args, **kwargs):
        raise RuntimeError(_dependency_error()["error"])

    def search_audio_proximity(*args, **kwargs):
        raise RuntimeError(_dependency_error()["error"])

    def get_memory_stats():
        return _dependency_error()

    def clear_memory():
        return 0

    def list_memories():
        return []

else:
    from .core import (
        clear_memory,
        get_memory_stats,
        list_memories,
        search_audio,
        search_audio_full,
        search_audio_proximity,
        transcribe_audio,
    )

# Optional dependencies (sentence-transformers, simple-diarizer, kokoro)
# are imported lazily inside handler functions so that installing them
# mid-session works without restarting the MCP server.


def send_response(response: dict) -> None:
    """Send JSON-RPC response to stdout."""
    output = json.dumps(response)
    sys.stdout.write(output + "\n")
    sys.stdout.flush()


def _strip_quarantine(path: str) -> None:
    """Remove macOS quarantine flag from a file."""
    import platform
    import subprocess

    if platform.system() == "Darwin":
        try:
            subprocess.run(
                ["xattr", "-d", "com.apple.quarantine", path], capture_output=True
            )
        except Exception:
            pass


def _write_output_file(
    output_path: str,
    rows: list,
    columns: list,
    bold_columns: list = None,
    keyword_column: str = None,
) -> str:
    """
    Write results to CSV or XLSX based on file extension.

    Args:
        output_path: File path (.csv or .xlsx)
        rows: List of dicts with data
        columns: Column keys to include
        bold_columns: Column keys to bold in XLSX
        keyword_column: Column key containing text with **bold** keywords
    Returns:
        Absolute path of written file
    """
    import os
    import re

    path = os.path.expanduser(output_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    bold_columns = bold_columns or []

    if path.endswith(".xlsx"):
        _write_xlsx(path, rows, columns, bold_columns, keyword_column)
    else:
        _write_csv(path, rows, columns)

    _strip_quarantine(path)
    return os.path.abspath(path)


def _write_csv(path: str, rows: list, columns: list) -> None:
    """Write plain CSV file."""
    import csv
    import io
    import re

    bold_pattern = re.compile(r"\*\*(.+?)\*\*")

    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header
    header_names = {
        "timestamp": "Timestamp",
        "text": "Text",
        "snippet": "Snippet",
        "keyword": "Keyword",
        "timestamp_seconds": "Seconds",
        "confidence": "Confidence",
        "match_type": "Match Type",
        "similarity": "Similarity",
        "source": "Source",
        "title": "Source",
    }
    writer.writerow([header_names.get(c, c.title()) for c in columns])

    for row in rows:
        vals = []
        for c in columns:
            v = row.get(c, "")
            if isinstance(v, str):
                v = bold_pattern.sub(r"\1", v)
                v = v.replace("...", "").strip()
            vals.append(v)
        writer.writerow(vals)

    with open(path, "w", newline="") as f:
        f.write(buf.getvalue())


def _write_xlsx(
    path: str, rows: list, columns: list, bold_columns: list, keyword_column: str = None
) -> None:
    """Write styled XLSX file with bold headers, timestamps, and keywords."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    except ImportError:
        # Fallback to CSV if openpyxl not installed
        _write_csv(path.replace(".xlsx", ".csv"), rows, columns)
        return

    import re

    bold_pattern = re.compile(r"\*\*(.+?)\*\*")

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"

    # Styles
    header_fill = PatternFill(
        start_color="1F1F1F", end_color="1F1F1F", fill_type="solid"
    )
    header_font_white = Font(bold=True, size=11, color="FFFFFF")
    bold_font = Font(bold=True, size=10)
    normal_font = Font(size=10)
    thin_border = Border(bottom=Side(style="thin", color="E0E0E0"))

    # Column names
    header_names = {
        "timestamp": "Timestamp",
        "text": "Text",
        "snippet": "Snippet",
        "keyword": "Keyword",
        "timestamp_seconds": "Seconds",
        "confidence": "Confidence",
        "match_type": "Match Type",
        "similarity": "Similarity",
        "source": "Source",
        "title": "Source",
    }

    # Write header row
    for col_idx, col_key in enumerate(columns, 1):
        cell = ws.cell(
            row=1, column=col_idx, value=header_names.get(col_key, col_key.title())
        )
        cell.font = header_font_white
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="left")

    # Write data rows
    for row_idx, row_data in enumerate(rows, 2):
        for col_idx, col_key in enumerate(columns, 1):
            val = row_data.get(col_key, "")
            if isinstance(val, str):
                val = bold_pattern.sub(r"\1", val)
                val = val.replace("...", "").strip()
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            if col_key in bold_columns:
                cell.font = bold_font
            else:
                cell.font = normal_font
            cell.border = thin_border
            cell.alignment = Alignment(wrap_text=True)

    # Auto-width columns
    for col_idx, col_key in enumerate(columns, 1):
        max_len = len(header_names.get(col_key, col_key))
        for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, min(len(str(cell.value)), 80))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = (
            max_len + 4
        )

    wb.save(path)


def send_error(id: Any, code: int, message: str) -> None:
    """Send JSON-RPC error response."""
    send_response(
        {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}
    )


def handle_initialize(id: Any, params: dict) -> None:
    """Handle initialize request."""
    send_response(
        {
            "jsonrpc": "2.0",
            "id": id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "augent", "version": "2026.2.28"},
            },
        }
    )


def handle_tools_list(id: Any) -> None:
    """Handle tools/list request."""
    send_response(
        {
            "jsonrpc": "2.0",
            "id": id,
            "result": {
                "tools": [
                    {
                        "name": "download_audio",
                        "description": "Download audio from video URLs at maximum speed. Built by Augent with speed optimizations (aria2c multi-connection, concurrent fragments). Downloads audio ONLY - never video. Supports YouTube, Vimeo, TikTok, Twitter, SoundCloud, and 1000+ sites.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "Video URL to download audio from (YouTube, Vimeo, TikTok, etc.)",
                                },
                                "output_dir": {
                                    "type": "string",
                                    "description": "Directory to save the audio file. Default: ~/Downloads",
                                },
                            },
                            "required": ["url"],
                        },
                    },
                    {
                        "name": "transcribe_audio",
                        "description": "Transcribe an audio file and return the full text with timestamps. Useful when you need the complete transcription rather than searching for specific keywords.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "audio_path": {
                                    "type": "string",
                                    "description": "Path to the audio file",
                                },
                                "model_size": {
                                    "type": "string",
                                    "enum": [
                                        "tiny",
                                        "base",
                                        "small",
                                        "medium",
                                        "large",
                                    ],
                                    "description": "Whisper model size. ALWAYS use tiny unless the user explicitly requests a different size. tiny is already highly accurate.",
                                },
                                "start": {
                                    "type": "number",
                                    "description": "Start transcription at this many seconds into the audio. Default: 0 (beginning)",
                                },
                                "duration": {
                                    "type": "number",
                                    "description": "Only transcribe this many seconds of audio. Example: 600 = first 10 minutes. Default: full file",
                                },
                                "output": {
                                    "type": "string",
                                    "description": "Optional file path to save transcription. Use .csv for plain data or .xlsx for styled spreadsheets with bold headers and formatting.",
                                },
                            },
                            "required": ["audio_path"],
                        },
                    },
                    {
                        "name": "search_audio",
                        "description": "Search audio files for keywords and return timestamped matches with context snippets. Useful for finding specific moments in podcasts, interviews, lectures, or any audio content.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "audio_path": {
                                    "type": "string",
                                    "description": "Path to the audio file (MP3, WAV, M4A, etc.)",
                                },
                                "keywords": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of keywords or phrases to search for",
                                },
                                "model_size": {
                                    "type": "string",
                                    "enum": [
                                        "tiny",
                                        "base",
                                        "small",
                                        "medium",
                                        "large",
                                    ],
                                    "description": "Whisper model size. ALWAYS use tiny unless the user explicitly requests a different size. tiny is already highly accurate.",
                                },
                                "include_full_text": {
                                    "type": "boolean",
                                    "description": "Include full transcription text in response. Default: false",
                                },
                                "output": {
                                    "type": "string",
                                    "description": "Optional file path to save results. Use .csv for plain data or .xlsx for styled spreadsheets with bold headers and formatting.",
                                },
                            },
                            "required": ["audio_path", "keywords"],
                        },
                    },
                    {
                        "name": "deep_search",
                        "description": "Search audio by meaning, not just keywords.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "audio_path": {
                                    "type": "string",
                                    "description": "Path to the audio file",
                                },
                                "query": {
                                    "type": "string",
                                    "description": "Natural language search query (e.g. 'discussion about funding challenges')",
                                },
                                "top_k": {
                                    "type": "integer",
                                    "description": "Number of results to return. Default: 5",
                                },
                                "model_size": {
                                    "type": "string",
                                    "enum": [
                                        "tiny",
                                        "base",
                                        "small",
                                        "medium",
                                        "large",
                                    ],
                                    "description": "Whisper model size. ALWAYS use tiny unless the user explicitly requests a different size. tiny is already highly accurate.",
                                },
                                "output": {
                                    "type": "string",
                                    "description": "Optional file path to save results. Use .csv for plain data or .xlsx for styled spreadsheets with bold headers and formatting.",
                                },
                                "context_words": {
                                    "type": "integer",
                                    "description": "Words of context per result. Default: 25. Use 150 for full evidence blocks when Claude needs to answer a question, not just find a moment.",
                                },
                                "dedup_seconds": {
                                    "type": "number",
                                    "description": "Merge matches within this many seconds of each other to avoid redundant results. Default: 0 (off). Use 60 for Q&A.",
                                },
                            },
                            "required": ["audio_path", "query"],
                        },
                    },
                    {
                        "name": "take_notes",
                        "description": "Take notes from a URL. Downloads audio, transcribes, and saves .txt to Desktop. This single tool handles the entire pipeline — download, transcribe, and save — when the user asks for notes, summaries, highlights, takeaways, eye-candy, quiz, or any formatted content from a video/audio URL. Returns audio_path for follow-up tools (chapters, search). Also used to SAVE formatted notes: call with save_content to write notes to the file from the previous take_notes call (no url needed).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "Video/audio URL to take notes from (YouTube, Vimeo, TikTok, Twitter, SoundCloud, etc.)",
                                },
                                "save_content": {
                                    "type": "string",
                                    "description": "Formatted notes content to save. When provided, writes this content to the file from the previous take_notes call. No url needed.",
                                },
                                "output_dir": {
                                    "type": "string",
                                    "description": "Directory to save the .txt notes file. Default: ~/Desktop",
                                },
                                "style": {
                                    "type": "string",
                                    "enum": [
                                        "tldr",
                                        "notes",
                                        "highlight",
                                        "eye-candy",
                                        "quiz",
                                    ],
                                    "description": "Note style. tldr > notes > highlight > eye-candy increases formatting richness. quiz generates questions. Default: notes. Pick based on what the user asks for.",
                                },
                                "model_size": {
                                    "type": "string",
                                    "enum": [
                                        "tiny",
                                        "base",
                                        "small",
                                        "medium",
                                        "large",
                                    ],
                                    "description": "Whisper model size. ALWAYS use tiny unless the user explicitly requests a different size. tiny is already highly accurate.",
                                },
                                "read_aloud": {
                                    "type": "boolean",
                                    "description": "Generate a spoken audio summary and embed it in the notes for Obsidian playback. Default: false",
                                },
                            },
                        },
                    },
                    {
                        "name": "chapters",
                        "description": "Auto-detect topic chapters in audio.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "audio_path": {
                                    "type": "string",
                                    "description": "Path to the audio file",
                                },
                                "sensitivity": {
                                    "type": "number",
                                    "description": "0.0 = many chapters, 1.0 = few chapters. Default: 0.4",
                                },
                                "model_size": {
                                    "type": "string",
                                    "enum": [
                                        "tiny",
                                        "base",
                                        "small",
                                        "medium",
                                        "large",
                                    ],
                                    "description": "Whisper model size. ALWAYS use tiny unless the user explicitly requests a different size. tiny is already highly accurate.",
                                },
                            },
                            "required": ["audio_path"],
                        },
                    },
                    {
                        "name": "batch_search",
                        "description": "Search multiple audio files for keywords in parallel. Ideal for processing podcast libraries, interview collections, or any batch of audio files. Returns aggregated results with file paths.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "audio_paths": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of paths to audio files",
                                },
                                "keywords": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of keywords or phrases to search for",
                                },
                                "model_size": {
                                    "type": "string",
                                    "enum": [
                                        "tiny",
                                        "base",
                                        "small",
                                        "medium",
                                        "large",
                                    ],
                                    "description": "Whisper model size. ALWAYS use tiny unless the user explicitly requests a different size. tiny is already highly accurate.",
                                },
                                "workers": {
                                    "type": "integer",
                                    "description": "Number of parallel workers. Default: 2",
                                },
                            },
                            "required": ["audio_paths", "keywords"],
                        },
                    },
                    {
                        "name": "text_to_speech",
                        "description": "Convert text to natural speech audio using Kokoro TTS. Saves an MP3 file. Runs in background — returns a job_id immediately. Call again with job_id to check status. Pass text for raw TTS, or file_path to read a notes file (strips markdown, skips metadata, embeds audio player).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "job_id": {
                                    "type": "string",
                                    "description": "Check status of a running TTS job. Pass the job_id returned from a previous call.",
                                },
                                "text": {
                                    "type": "string",
                                    "description": "Text to convert to speech. Either text or file_path is required.",
                                },
                                "file_path": {
                                    "type": "string",
                                    "description": "Path to a notes file to read aloud. Strips markdown formatting, skips metadata, generates MP3, and embeds audio player in the file.",
                                },
                                "voice": {
                                    "type": "string",
                                    "description": "Voice ID. American English: af_heart (female, default), af_bella, af_nicole, af_nova, af_sky, am_adam (male), am_eric, am_michael. British English: bf_emma, bf_lily, bm_daniel, bm_george. Also supports Spanish, French, Japanese, Chinese voices.",
                                },
                                "output_dir": {
                                    "type": "string",
                                    "description": "Directory to save the MP3 file. Default: ~/Desktop",
                                },
                                "output_filename": {
                                    "type": "string",
                                    "description": "Custom filename. Auto-generated if not set.",
                                },
                                "speed": {
                                    "type": "number",
                                    "description": "Speech speed multiplier. Default: 1.0",
                                },
                            },
                        },
                    },
                    {
                        "name": "search_proximity",
                        "description": "Find where one keyword appears near another keyword in audio. Useful for finding contextual discussions, e.g., 'startup' near 'funding'.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "audio_path": {
                                    "type": "string",
                                    "description": "Path to the audio file",
                                },
                                "keyword1": {
                                    "type": "string",
                                    "description": "Primary keyword to find",
                                },
                                "keyword2": {
                                    "type": "string",
                                    "description": "Secondary keyword that must appear nearby",
                                },
                                "max_distance": {
                                    "type": "integer",
                                    "description": "Maximum number of words between keywords. Default: 30",
                                },
                                "model_size": {
                                    "type": "string",
                                    "enum": [
                                        "tiny",
                                        "base",
                                        "small",
                                        "medium",
                                        "large",
                                    ],
                                    "description": "Whisper model size. ALWAYS use tiny unless the user explicitly requests a different size. tiny is already highly accurate.",
                                },
                                "output": {
                                    "type": "string",
                                    "description": "Optional file path to save results. Use .csv for plain data or .xlsx for styled spreadsheets with bold headers and formatting.",
                                },
                            },
                            "required": ["audio_path", "keyword1", "keyword2"],
                        },
                    },
                    {
                        "name": "identify_speakers",
                        "description": "Identify who speaks when in audio.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "audio_path": {
                                    "type": "string",
                                    "description": "Path to the audio file",
                                },
                                "num_speakers": {
                                    "type": "integer",
                                    "description": "Number of speakers if known. Auto-detects if not set.",
                                },
                                "model_size": {
                                    "type": "string",
                                    "enum": [
                                        "tiny",
                                        "base",
                                        "small",
                                        "medium",
                                        "large",
                                    ],
                                    "description": "Whisper model size. ALWAYS use tiny unless the user explicitly requests a different size. tiny is already highly accurate.",
                                },
                            },
                            "required": ["audio_path"],
                        },
                    },
                    {
                        "name": "list_files",
                        "description": "List media files in a directory.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "directory": {
                                    "type": "string",
                                    "description": "Directory path to search",
                                },
                                "pattern": {
                                    "type": "string",
                                    "description": "Glob pattern for matching files. Default: all common media formats",
                                },
                                "recursive": {
                                    "type": "boolean",
                                    "description": "Search subdirectories. Default: false",
                                },
                            },
                            "required": ["directory"],
                        },
                    },
                    {
                        "name": "list_memories",
                        "description": "List all stored transcriptions with their titles, durations, dates, and file paths to markdown files. Useful for browsing what has already been transcribed.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "memory_stats",
                        "description": "View transcription memory statistics including number of stored files and total duration.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "clear_memory",
                        "description": "Clear the transcription memory to free disk space.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "search_memory",
                        "description": "Search across ALL stored transcriptions. No audio_path needed, queries everything in memory. Default mode is 'keyword' (literal match). Use 'semantic' mode for meaning-based search.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query. For keyword mode: a word or phrase to find literally. For semantic mode: a natural language description (e.g. 'discussion about funding challenges').",
                                },
                                "mode": {
                                    "type": "string",
                                    "enum": ["keyword", "semantic"],
                                    "description": "Search mode. 'keyword' (default) finds segments containing the exact word/phrase. 'semantic' finds segments similar in meaning.",
                                },
                                "top_k": {
                                    "type": "integer",
                                    "description": "Number of results to return. Default: 10",
                                },
                                "output": {
                                    "type": "string",
                                    "description": "Optional file path to save results. Use .csv for plain data or .xlsx for styled spreadsheets with bold headers and formatting.",
                                },
                                "context_words": {
                                    "type": "integer",
                                    "description": "Words of context per result. Default: 25. Use 150 for full evidence blocks when Claude needs to answer a question. Semantic mode only.",
                                },
                                "dedup_seconds": {
                                    "type": "number",
                                    "description": "Merge matches within this many seconds of each other. Default: 0 (off). Semantic mode only.",
                                },
                            },
                            "required": ["query"],
                        },
                    },
                ]
            },
        }
    )


def handle_tools_call(id: Any, params: dict) -> None:
    """Handle tools/call request."""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    try:
        if tool_name == "download_audio":
            result = handle_download_audio(arguments)
        elif tool_name == "transcribe_audio":
            result = handle_transcribe_audio(arguments)
        elif tool_name == "search_audio":
            result = handle_search_audio(arguments)
        elif tool_name == "deep_search":
            result = handle_deep_search(arguments)
        elif tool_name == "take_notes":
            result = handle_take_notes(arguments)
        elif tool_name == "chapters":
            result = handle_chapters(arguments)
        elif tool_name == "batch_search":
            result = handle_batch_search(arguments)
        elif tool_name == "text_to_speech":
            result = handle_text_to_speech(arguments)
        elif tool_name == "search_proximity":
            result = handle_search_proximity(arguments)
        elif tool_name == "identify_speakers":
            result = handle_identify_speakers(arguments)
        elif tool_name == "list_files":
            result = handle_list_files(arguments)
        elif tool_name == "list_memories":
            result = handle_list_memories(arguments)
        elif tool_name == "memory_stats":
            result = handle_memory_stats(arguments)
        elif tool_name == "clear_memory":
            result = handle_clear_memory(arguments)
        elif tool_name == "search_memory":
            result = handle_search_memory(arguments)
        else:
            send_error(id, -32602, f"Unknown tool: {tool_name}")
            return

        send_response(
            {
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                },
            }
        )

    except FileNotFoundError as e:
        send_error(id, -32602, str(e))
    except ValueError as e:
        send_error(id, -32602, str(e))
    except Exception as e:
        send_error(id, -32603, f"Error: {str(e)}")


def handle_download_audio(arguments: dict) -> dict:
    """Handle download_audio tool call."""
    import os
    import re
    import shutil
    import subprocess

    url = arguments.get("url")
    output_dir = arguments.get("output_dir", os.path.expanduser("~/Downloads"))

    if not url:
        raise ValueError("Missing required parameter: url")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Check for yt-dlp
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp not found. Install with: brew install yt-dlp")

    # Check for aria2c (optional but recommended)
    has_aria2c = shutil.which("aria2c") is not None

    # Build command
    cmd = [
        "yt-dlp",
        "-f",
        "bestaudio",
        "--concurrent-fragments",
        "4",
        "--no-playlist",
        "-o",
        f"{output_dir}/%(title)s.%(ext)s",
        "--print",
        "after_move:filepath",  # Print the final file path
    ]

    if has_aria2c:
        cmd.extend(
            ["--downloader", "aria2c", "--downloader-args", "aria2c:-x 16 -s 16 -k 1M"]
        )

    cmd.append(url)

    # Run download
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        error_msg = result.stderr.strip() or "Download failed"
        raise RuntimeError(f"Download failed: {error_msg}")

    # Extract the output file path from stdout
    output_lines = result.stdout.strip().split("\n")
    output_file = output_lines[-1] if output_lines else None

    # Get file info if available
    file_info = {}
    if output_file and os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        file_info = {
            "path": output_file,
            "filename": os.path.basename(output_file),
            "size_mb": round(file_size / (1024 * 1024), 2),
        }

    return {
        "success": True,
        "url": url,
        "output_dir": output_dir,
        "file": file_info,
        "aria2c_used": has_aria2c,
        "message": (
            f"Audio downloaded to {output_file}" if output_file else "Download complete"
        ),
    }


def handle_search_audio(arguments: dict) -> dict:
    """Handle search_audio tool call."""
    audio_path = arguments.get("audio_path")
    keywords = arguments.get("keywords", [])
    model_size = arguments.get("model_size", "tiny")
    include_full = arguments.get("include_full_text", False)
    output = arguments.get("output")

    if not audio_path:
        raise ValueError("Missing required parameter: audio_path")
    if not keywords:
        raise ValueError("Missing required parameter: keywords")

    if include_full:
        result = search_audio_full(audio_path, keywords, model_size=model_size)
    else:
        result = search_audio(audio_path, keywords, model_size=model_size)

    result["model_used"] = model_size

    # Write output file if requested
    if output:
        # Flatten grouped results into rows
        rows = []
        for kw, matches in result.items():
            if isinstance(matches, list):
                for m in matches:
                    rows.append(
                        {
                            "keyword": kw,
                            "timestamp": m.get("timestamp", ""),
                            "timestamp_seconds": m.get("timestamp_seconds", 0),
                            "snippet": m.get("snippet", ""),
                        }
                    )
        if rows:
            result["output_path"] = _write_output_file(
                output,
                rows,
                columns=["keyword", "timestamp", "snippet"],
                bold_columns=["keyword", "timestamp"],
            )

    return result


def handle_transcribe_audio(arguments: dict) -> dict:
    """Handle transcribe_audio tool call."""
    import subprocess
    import tempfile

    audio_path = arguments.get("audio_path")
    model_size = arguments.get("model_size", "tiny")
    start = arguments.get("start")
    duration = arguments.get("duration")
    output = arguments.get("output")

    if not audio_path:
        raise ValueError("Missing required parameter: audio_path")

    # If start or duration specified, trim audio with ffmpeg first
    trimmed_path = None
    if start is not None or duration is not None:
        trimmed_path = tempfile.mktemp(suffix=".webm")
        cmd = ["ffmpeg", "-y", "-i", audio_path]
        if start is not None:
            cmd.extend(["-ss", str(start)])
        if duration is not None:
            cmd.extend(["-t", str(duration)])
        cmd.extend(["-vn", "-acodec", "copy", trimmed_path])
        subprocess.run(cmd, capture_output=True, check=True)
        audio_path = trimmed_path

    try:
        result = transcribe_audio(audio_path, model_size)
    finally:
        # Clean up temp file
        if trimmed_path and os.path.exists(trimmed_path):
            os.remove(trimmed_path)

    # Build per-segment timestamps
    segments = []
    for seg in result.get("segments", []):
        s = seg["start"]
        # Offset timestamps back if start was specified
        if start:
            s += start
        e = seg["end"]
        if start:
            e += start
        minutes_s, secs_s = int(s // 60), int(s % 60)
        segments.append(
            {
                "start": round(s, 1),
                "end": round(e, 1),
                "timestamp": f"{minutes_s}:{secs_s:02d}",
                "text": seg["text"].strip(),
            }
        )

    # Cap response size to prevent token overflow in Claude Code.
    # For large transcriptions, truncate text and suggest using output param.
    full_text = result["text"]
    max_chars = 12000
    max_segments = 200
    truncated = len(full_text) > max_chars or len(segments) > max_segments

    if truncated:
        capped_text = (
            full_text[:max_chars]
            + "\n\n[... truncated — use the output parameter to export full transcription to .csv or .xlsx ...]"
        )
        capped_segments = segments[:max_segments]
    else:
        capped_text = full_text
        capped_segments = segments

    response = {
        "text": capped_text,
        "language": result["language"],
        "duration": result["duration"],
        "duration_formatted": f"{int(result['duration'] // 60)}:{int(result['duration'] % 60):02d}",
        "segments": capped_segments,
        "segment_count": len(segments),
        "cached": result.get("cached", False),
        "model_used": model_size,
    }

    if truncated:
        response["truncated"] = True
        response["full_segment_count"] = len(segments)
        response["hint"] = (
            "Response was truncated to prevent overflow. Use the output parameter (e.g. output: '~/Desktop/transcript.csv') to get the full transcription."
        )

    # Write output file if requested
    if output:
        response["output_path"] = _write_output_file(
            output,
            segments,
            columns=["timestamp", "text"],
            bold_columns=["timestamp"],
        )

    return response


def handle_search_proximity(arguments: dict) -> dict:
    """Handle search_proximity tool call."""
    audio_path = arguments.get("audio_path")
    keyword1 = arguments.get("keyword1")
    keyword2 = arguments.get("keyword2")
    max_distance = arguments.get("max_distance", 30)
    model_size = arguments.get("model_size", "tiny")
    output = arguments.get("output")

    if not audio_path:
        raise ValueError("Missing required parameter: audio_path")
    if not keyword1:
        raise ValueError("Missing required parameter: keyword1")
    if not keyword2:
        raise ValueError("Missing required parameter: keyword2")

    matches = search_audio_proximity(
        audio_path, keyword1, keyword2, max_distance=max_distance, model_size=model_size
    )

    result = {
        "query": f"'{keyword1}' within {max_distance} words of '{keyword2}'",
        "match_count": len(matches),
        "matches": matches,
        "model_used": model_size,
    }

    # Write output file if requested
    if output and matches:
        result["output_path"] = _write_output_file(
            output,
            matches,
            columns=["timestamp", "snippet"],
            bold_columns=["timestamp"],
        )

    return result


def handle_batch_search(arguments: dict) -> dict:
    """Handle batch_search tool call."""
    import os
    from concurrent.futures import ThreadPoolExecutor, as_completed

    audio_paths = arguments.get("audio_paths", [])
    keywords = arguments.get("keywords", [])
    model_size = arguments.get("model_size", "tiny")
    workers = arguments.get("workers", 2)

    if not audio_paths:
        raise ValueError("Missing required parameter: audio_paths")
    if not keywords:
        raise ValueError("Missing required parameter: keywords")

    # Validate all paths exist
    valid_paths = []
    errors = []
    for path in audio_paths:
        if os.path.exists(path):
            valid_paths.append(path)
        else:
            errors.append({"path": path, "error": "File not found"})

    results = {}

    def process_file(path):
        try:
            return path, search_audio(path, keywords, model_size=model_size)
        except Exception as e:
            return path, {"error": str(e)}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_file, p): p for p in valid_paths}
        for future in as_completed(futures):
            path, result = future.result()
            results[path] = result

    # Aggregate stats
    total_matches = 0
    for _path, file_results in results.items():
        if "error" not in file_results:
            for _kw, matches in file_results.items():
                total_matches += len(matches)

    return {
        "files_processed": len(valid_paths),
        "files_with_errors": len(errors),
        "total_matches": total_matches,
        "results": results,
        "errors": errors if errors else None,
        "model_used": model_size,
    }


def handle_list_files(arguments: dict) -> dict:
    """Handle list_files tool call."""
    import glob as glob_module
    import os

    DEFAULT_PATTERNS = [
        "*.mp3",
        "*.m4a",
        "*.wav",
        "*.webm",
        "*.mp4",
        "*.mkv",
        "*.ogg",
        "*.flac",
    ]

    directory = arguments.get("directory")
    pattern = arguments.get("pattern")
    recursive = arguments.get("recursive", False)

    if not directory:
        raise ValueError("Missing required parameter: directory")

    if not os.path.isdir(directory):
        raise ValueError(f"Directory not found: {directory}")

    # Build search pattern(s)
    files = []
    if pattern:
        patterns = [pattern]
    else:
        patterns = DEFAULT_PATTERNS

    for p in patterns:
        if recursive:
            search_pattern = os.path.join(directory, "**", p)
            files.extend(glob_module.glob(search_pattern, recursive=True))
        else:
            search_pattern = os.path.join(directory, p)
            files.extend(glob_module.glob(search_pattern))

    # Deduplicate and sort
    files = sorted(set(files))

    # Get file info
    audio_files = []
    for f in files:
        try:
            size = os.path.getsize(f)
            audio_files.append(
                {
                    "path": f,
                    "name": os.path.basename(f),
                    "size_mb": round(size / (1024 * 1024), 2),
                }
            )
        except OSError:
            pass

    return {
        "directory": directory,
        "pattern": pattern,
        "recursive": recursive,
        "count": len(audio_files),
        "files": audio_files,
    }


def handle_memory_stats(arguments: dict) -> dict:
    """Handle memory_stats tool call."""
    return get_memory_stats()


def handle_clear_memory(arguments: dict) -> dict:
    """Handle clear_memory tool call."""
    count = clear_memory()
    return {"cleared": count, "message": f"Cleared {count} stored transcription(s)"}


def handle_list_memories(arguments: dict) -> dict:
    """Handle list_memories tool call."""
    entries = list_memories()
    return {
        "count": len(entries),
        "transcriptions": entries,
        "message": f"Found {len(entries)} stored transcription(s)",
    }


def _get_style_instruction(
    style: str,
    read_aloud: bool = False,
    output_dir: str = "~/Desktop",
    safe_title: str = "",
    txt_path: str = "",
) -> str:
    """Return formatting instructions for a given note style."""

    base_prefix = (
        "IMPORTANT: You MUST now format the notes and save them by calling take_notes again with save_content. "
        "Do NOT use the Write or Edit tools on notes files — ALWAYS use take_notes(save_content=...) for both initial save and any subsequent edits. "
        "Do NOT leave the raw transcription as-is. Do NOT create .md files. "
        "For any follow-up tool calls (chapters, search, deep_search, etc.), use the audio_path field from this response — do NOT guess the filename. "
    )
    label = "Quiz" if style == "quiz" else "Notes"
    base_suffix = (
        '\n\nSave the final notes by calling: take_notes(save_content="<your formatted notes>"). '
        "Do NOT use the Write tool. "
        f"After saving, respond ONLY with: Done. {label} saved to ~/Desktop/<filename>"
    )

    if read_aloud:
        import os as _os
        import shutil as _shutil

        _obsidian_installed = _os.path.exists("/Applications/Obsidian.app") or bool(
            _shutil.which("obsidian")
        )
        audio_filename = f"{safe_title}.mp3" if safe_title else "notes_audio.mp3"
        if _obsidian_installed:
            embed_instruction = (
                f"After TTS completes, prepend ![[{audio_filename}]] on the very first line "
                f"(before the title) and `> Press Cmd+E before playing — prevents audio from pausing on scroll` "
                "on the line after the embed, then save by calling take_notes(save_content=...) with the full updated content. "
            )
        else:
            embed_instruction = ""
        base_suffix = (
            '\n\nSave the final notes by calling: take_notes(save_content="<your formatted notes>"). '
            "Do NOT use the Write tool. "
            "THEN: Take the notes you just wrote — SKIP the title, source URL, duration, date, and any metadata lines at the top. Start from the first real content section heading. Take that content and "
            "strip the markdown formatting (remove #, **, -, >, ![], ---, callout syntax, links) "
            "so it reads as plain text. Keep every word and all the information exactly as written — "
            "do NOT rewrite or summarize, just clean the formatting so TTS can read it naturally. "
            "Section headers become spoken section titles. "
            "Run the text_to_speech tool with that spoken script, "
            f'output_dir="{output_dir}", output_filename="{audio_filename}". '
            + embed_instruction
            + f"After everything, respond ONLY with: Done. {label} saved to ~/Desktop/<filename>"
        )

    styles = {
        "tldr": (
            "Create the shortest possible summary. Must fit on one screen.\n"
            "\n"
            "FORMAT:\n"
            "- Title as a top header\n"
            "- Source URL | Duration | Date on one line\n"
            "- ---\n"
            "- One 2-3 sentence overview paragraph\n"
            "- 5-8 bullet points max, each one line\n"
            "- **Bold** the single most important term or name in each bullet\n"
            "- No sections, no headers, no callouts, no quotes — just clean bullets\n"
            "- End with one bold takeaway line\n"
        ),
        "notes": (
            "Create clean, structured notes with clear hierarchy.\n"
            "\n"
            "FORMAT:\n"
            "- Title as a top header\n"
            "- Metadata block: Source URL, Duration, Date\n"
            "- ---\n"
            "- 3-6 section headers based on the main topics\n"
            "- Nested bullet points under each section (2 levels max)\n"
            "- **Bold** key terms and names throughout\n"
            "- Short paragraphs only — never more than 3 lines\n"
            "- One > blockquote if there's a standout quote worth preserving\n"
            "- Keep it scannable — someone should grasp the content in 60 seconds\n"
        ),
        "highlight": (
            "Create formatted notes with visual emphasis on key insights.\n"
            "\n"
            "FORMAT:\n"
            "- Title as a top header\n"
            "- Metadata block: Source URL, Duration, Date\n"
            "- ---\n"
            "- Section headers for each major topic\n"
            "- Nested bullet points with **bold key terms**\n"
            "- Use > [!tip] callout blocks for the 2-4 most important insights\n"
            "- Use > [!info] callout blocks for definitions or context\n"
            "- Use > blockquotes with timestamps for 2-3 key direct quotes\n"
            "- Use **bold** and *italic* generously for emphasis\n"
            "- Add a --- separator between major sections\n"
            "- End with a Key Takeaways section using a > [!summary] callout\n"
        ),
        "eye-candy": (
            "Create the most visually rich, beautifully formatted notes possible. "
            "Every section should be a visual experience — the reader should absorb "
            "the content by scanning, not reading.\n"
            "\n"
            "FORMAT:\n"
            "- Title as a top header\n"
            "- Metadata block: Source URL, Duration, Date\n"
            "- ---\n"
            "- Section headers for every topic shift\n"
            "- Nested bullet points (up to 3 levels) with **bold** and *italic*\n"
            "- > [!tip] callout blocks for key insights (use liberally, 4-6 throughout)\n"
            "- > [!info] callout blocks for context, background, definitions\n"
            "- > [!warning] callout blocks for common mistakes or misconceptions\n"
            "- > [!example] callout blocks for concrete examples mentioned\n"
            "- > blockquotes with timestamps for 3-5 standout direct quotes\n"
            "- Tables anywhere a comparison or list of items is discussed\n"
            "- --- separators between major sections\n"
            "- Checklists (- [ ]) for any action items or recommendations\n"
            "- End with:\n"
            "  1. A > [!summary] Key Takeaways callout with numbered list\n"
            "  2. A table of Related Topics / Further Reading if applicable\n"
            "\n"
            "The goal: someone opens this file in Obsidian and says 'wow'.\n"
        ),
        "quiz": (
            "Generate a multiple-choice quiz from the content. Do NOT write notes.\n"
            "\n"
            "FORMAT:\n"
            "- Title as a top header with 'Quiz' appended\n"
            "- Metadata block: Source URL, Duration, Date\n"
            "- ---\n"
            "- 10-15 multiple-choice questions\n"
            "- Each question MUST follow this EXACT structure:\n"
            "\n"
            "### 1. **Question text here?**\n"
            "\n"
            "A) First option\n"
            "B) Second option\n"
            "C) Third option\n"
            "D) Fourth option\n"
            "\n"
            "- ---\n"
            "- Answer Key section at the bottom with this EXACT format:\n"
            "\n"
            "## Answer Key\n"
            "\n"
            "**1. B** — Explanation of why B is correct.\n"
            "**2. A** — Explanation of why A is correct.\n"
            "**3. D** — Explanation of why D is correct.\n"
            "\n"
            "Each answer on its own line. Bold number and letter, em dash, then explanation. No grouping, no compact rows, no bullet lists.\n"
            "\n"
            "Questions should test real understanding, not trivial details.\n"
        ),
    }

    body = styles.get(style, styles["notes"])
    return base_prefix + body + base_suffix


_last_notes_path = None


def handle_take_notes(arguments: dict) -> dict:
    """Handle take_notes tool call - download, transcribe, save .txt to Desktop."""
    import os
    import re

    global _last_notes_path

    # --- Save mode: write formatted notes to the file from the previous call ---
    save_content = arguments.get("save_content")
    if save_content is not None:
        if not _last_notes_path:
            raise ValueError(
                "No previous take_notes path. Call take_notes with a url first."
            )
        # Post-process: convert plain A)/B)/C)/D) answer lines to checkbox syntax
        had_bare = bool(re.search(r"^\s*[A-D]\)", save_content, flags=re.MULTILINE))
        save_content = re.sub(
            r"^(\s*)([A-D]\))", r"- [ ] \2", save_content, flags=re.MULTILINE
        )
        has_checkboxes = "- [ ]" in save_content
        with open(_last_notes_path, "w", encoding="utf-8") as f:
            f.write(save_content)
        # Debug log
        import datetime

        with open(os.path.expanduser("~/.augent/checkbox_debug.log"), "a") as dbg:
            dbg.write(
                f"{datetime.datetime.now()} | path={_last_notes_path} | had_bare={had_bare} | has_checkboxes={has_checkboxes} | size={len(save_content)}\n"
            )
        return {
            "success": True,
            "saved_to": _last_notes_path,
            "size": len(save_content),
            "debug_checkbox": {
                "had_bare_options": had_bare,
                "has_checkboxes_after": has_checkboxes,
            },
        }

    url = arguments.get("url")
    output_dir = arguments.get("output_dir", os.path.expanduser("~/Desktop"))
    model_size = arguments.get("model_size", "tiny")
    style = arguments.get("style", "notes")
    read_aloud = arguments.get("read_aloud", False)

    if not url:
        raise ValueError("Missing required parameter: url")

    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Download audio to ~/Downloads
    download_result = handle_download_audio({"url": url})

    if not download_result.get("success"):
        raise RuntimeError(
            "Download failed: " + download_result.get("message", "unknown error")
        )

    file_info = download_result.get("file", {})
    if not file_info.get("path"):
        raise RuntimeError("Download succeeded but output file not found")
    audio_path = file_info["path"]
    title = os.path.splitext(file_info["filename"])[0]

    # Step 2: Transcribe
    result = transcribe_audio(audio_path, model_size)
    text = result["text"]
    duration = result["duration"]

    # Step 3: Save raw transcription as .txt on Desktop
    # Clean title for filename (remove special chars)
    safe_title = re.sub(r"[^\w\s\-]", "", title)
    safe_title = re.sub(r"\s+", " ", safe_title).strip()
    if not safe_title:
        safe_title = "notes"
    txt_filename = f"{safe_title}.txt"
    txt_path = os.path.join(output_dir, txt_filename)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"Source: {url}\n")
        f.write(f"Duration: {int(duration // 60)}:{int(duration % 60):02d}\n")
        f.write(f"Title: {title}\n")
        f.write("=" * 60 + "\n\n")
        f.write(text)

    _last_notes_path = txt_path

    # Style-specific formatting instructions
    instruction = _get_style_instruction(
        style,
        read_aloud=read_aloud,
        output_dir=output_dir,
        safe_title=safe_title,
        txt_path=txt_path,
    )

    # Cap transcription in response to prevent token overflow in Claude Code.
    # Full transcript is already saved to txt_path — Claude reads the file.
    max_chars = 12000
    if len(text) > max_chars:
        truncated_text = (
            text[:max_chars]
            + f"\n\n[... truncated — full transcript saved to {txt_path} — read the file for complete text ...]"
        )
    else:
        truncated_text = text

    return {
        "success": True,
        "write_to": txt_path,
        "audio_path": audio_path,
        "instruction": instruction,
        "title": title,
        "duration": duration,
        "duration_formatted": f"{int(duration // 60)}:{int(duration % 60):02d}",
        "language": result["language"],
        "cached": result.get("cached", False),
        "model_used": model_size,
        "style": style,
        "transcription": truncated_text,
    }


def handle_identify_speakers(arguments: dict) -> dict:
    """Handle identify_speakers tool call."""
    try:
        from .speakers import identify_speakers
    except ImportError as err:
        raise RuntimeError(
            "Missing dependencies: simple-diarizer. "
            "Install with: pip install simple-diarizer"
        ) from err

    audio_path = arguments.get("audio_path")
    model_size = arguments.get("model_size", "tiny")
    num_speakers = arguments.get("num_speakers")

    if not audio_path:
        raise ValueError("Missing required parameter: audio_path")

    result = identify_speakers(
        audio_path,
        model_size=model_size,
        num_speakers=num_speakers,
    )

    return {
        "speakers": result["speakers"],
        "segment_count": len(result["segments"]),
        "segments": result["segments"],
        "duration": result["duration"],
        "duration_formatted": result["duration_formatted"],
        "language": result["language"],
        "cached": result.get("cached", False),
        "model_used": model_size,
    }


def handle_search_memory(arguments: dict) -> dict:
    """Handle search_memory tool call."""
    query = arguments.get("query")
    mode = arguments.get("mode", "keyword")
    top_k = arguments.get("top_k", 10)
    output = arguments.get("output")
    context_words = arguments.get("context_words", 25)
    dedup_seconds = arguments.get("dedup_seconds", 0)

    if not query:
        raise ValueError("Missing required parameter: query")

    if mode == "semantic":
        try:
            from .embeddings import search_memory
        except ImportError as err:
            raise RuntimeError(
                "Missing dependencies: sentence-transformers. "
                "Install with: pip install sentence-transformers"
            ) from err
        return search_memory(
            query,
            top_k=top_k,
            mode="semantic",
            output=output,
            context_words=context_words,
            dedup_seconds=dedup_seconds,
        )
    else:
        from .embeddings import search_memory

        return search_memory(query, top_k=top_k, mode="keyword", output=output)


def handle_deep_search(arguments: dict) -> dict:
    """Handle deep_search tool call."""
    try:
        from .embeddings import deep_search
    except ImportError as err:
        raise RuntimeError(
            "Missing dependencies: sentence-transformers. "
            "Install with: pip install sentence-transformers"
        ) from err

    audio_path = arguments.get("audio_path")
    query = arguments.get("query")
    model_size = arguments.get("model_size", "tiny")
    top_k = arguments.get("top_k", 5)
    output = arguments.get("output")
    context_words = arguments.get("context_words", 25)
    dedup_seconds = arguments.get("dedup_seconds", 0)

    if not audio_path:
        raise ValueError("Missing required parameter: audio_path")
    if not query:
        raise ValueError("Missing required parameter: query")

    result = deep_search(
        audio_path,
        query,
        model_size=model_size,
        top_k=top_k,
        context_words=context_words,
        dedup_seconds=dedup_seconds,
    )

    # Write output file if requested
    if output and result.get("results"):
        result["output_path"] = _write_output_file(
            output,
            result["results"],
            columns=["timestamp", "text", "similarity"],
            bold_columns=["timestamp"],
        )

    return result


def handle_chapters(arguments: dict) -> dict:
    """Handle chapters tool call."""
    try:
        from .embeddings import detect_chapters
    except ImportError as err:
        raise RuntimeError(
            "Missing dependencies: sentence-transformers. "
            "Install with: pip install sentence-transformers"
        ) from err

    audio_path = arguments.get("audio_path")
    model_size = arguments.get("model_size", "tiny")
    sensitivity = arguments.get("sensitivity", 0.4)

    if not audio_path:
        raise ValueError("Missing required parameter: audio_path")

    result = detect_chapters(
        audio_path,
        model_size=model_size,
        sensitivity=sensitivity,
    )

    # Trim chapter text to a short preview to avoid massive responses (~17k tokens)
    for chapter in result.get("chapters", []):
        text = chapter.get("text", "")
        words = text.split()
        if len(words) > 30:
            chapter["text"] = " ".join(words[:30]) + "..."

    return result


_tts_jobs = {}


def handle_text_to_speech(arguments: dict) -> dict:
    """Handle text_to_speech tool call. Runs in background subprocess, returns instantly."""
    import os
    import shutil
    import subprocess
    import tempfile
    import uuid

    # Check status of a running job
    job_id = arguments.get("job_id")
    if job_id:
        job = _tts_jobs.get(job_id)
        if not job:
            raise ValueError(f"Unknown job: {job_id}")
        proc = job["proc"]
        poll = proc.poll()
        if poll is None:
            return {
                "status": "generating",
                "job_id": job_id,
                "message": "TTS is still running. Check again in a few seconds.",
            }
        # Done — read result
        stdout = proc.stdout.read()
        proc.stdout.close()
        try:
            os.unlink(job["script"])
        except OSError:
            pass
        if poll != 0:
            del _tts_jobs[job_id]
            raise RuntimeError("TTS generation failed")
        result = json.loads(stdout.strip())
        if "error" in result:
            del _tts_jobs[job_id]
            raise RuntimeError(result["error"])
        del _tts_jobs[job_id]
        result["status"] = "complete"
        result["job_id"] = job_id
        return result

    text = arguments.get("text")
    file_path = arguments.get("file_path")
    voice = arguments.get("voice", "af_heart")
    output_dir = arguments.get("output_dir", "~/Desktop")
    output_filename = arguments.get("output_filename")
    speed = arguments.get("speed", 1.0)

    if not text and not file_path:
        raise ValueError("Either text or file_path is required")

    # Build a Python script to run TTS in a completely separate process
    script = f"""
import json, sys, os
_real_stdout = os.dup(1)
sys.stdout = open('/dev/null', 'w')
sys.stderr = open('/dev/null', 'w')
os.dup2(os.open('/dev/null', os.O_WRONLY), 1)
os.dup2(os.open('/dev/null', os.O_WRONLY), 2)
from augent.tts import text_to_speech, read_aloud
try:
    if {repr(file_path)}:
        result = read_aloud({repr(file_path)}, voice={repr(voice)}, speed={speed})
    else:
        result = text_to_speech(
            text={repr(text)},
            voice={repr(voice)},
            output_dir={repr(output_dir)},
            output_filename={repr(output_filename)},
            speed={speed},
        )
    os.dup2(_real_stdout, 1)
    sys.stdout = os.fdopen(_real_stdout, 'w')
    print(json.dumps(result))
except Exception as e:
    os.dup2(_real_stdout, 1)
    sys.stdout = os.fdopen(_real_stdout, 'w')
    print(json.dumps({{"error": str(e)}}))
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script)
        script_path = f.name

    python_bin = shutil.which("python3") or sys.executable
    proc = subprocess.Popen(
        [python_bin, script_path],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    job_id = str(uuid.uuid4())[:8]
    _tts_jobs[job_id] = {"proc": proc, "script": script_path}

    return {
        "status": "started",
        "job_id": job_id,
        "message": f"TTS generation started in background. Call text_to_speech with job_id='{job_id}' to check status.",
    }


def handle_request(request: dict) -> None:
    """Route JSON-RPC request to appropriate handler."""
    method = request.get("method")
    id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        handle_initialize(id, params)
    elif method == "notifications/initialized":
        pass  # No response needed for notifications
    elif method == "tools/list":
        handle_tools_list(id)
    elif method == "tools/call":
        handle_tools_call(id, params)
    else:
        if id is not None:
            send_error(id, -32601, f"Method not found: {method}")


def main() -> None:
    """Main MCP server loop."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            handle_request(request)
        except json.JSONDecodeError:
            send_error(None, -32700, "Parse error")
        except Exception as e:
            send_error(None, -32603, f"Internal error: {str(e)}")


if __name__ == "__main__":
    main()
