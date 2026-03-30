"""
Augent CLI - Command line interface for audio keyword search

Features:
- Single file and batch processing
- Multiple output formats (JSON, CSV, SRT, VTT, Markdown)
- Clip extraction
- Proximity search
- Live progress output
- Cache management
"""

import argparse
import glob
import json
import os
import platform
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional


def _strip_quarantine(path: str) -> None:
    """Remove macOS quarantine flag from a file."""
    if platform.system() == "Darwin":
        try:
            subprocess.run(
                ["xattr", "-d", "com.apple.quarantine", path], capture_output=True
            )
        except Exception:
            pass


from .clips import export_clips
from .core import (
    TranscriptionProgress,
    clear_memory,
    clear_model_cache,
    get_memory_stats,
    list_memories,
    search_audio,
    search_audio_full,
    search_audio_proximity,
    transcribe_audio,
    transcribe_audio_streaming,
)
from .export import export_matches, export_transcription
from .search import find_keyword_matches


def print_progress(progress: TranscriptionProgress, quiet: bool = False):
    """Print progress update to stderr."""
    if quiet:
        return

    if progress.status == "loading_model":
        print(f"\r{progress.message}", end="", file=sys.stderr)
    elif progress.status == "transcribing":
        print(f"\r{progress.message}", end="", file=sys.stderr)
    elif progress.status == "segment":
        print(f"\n  {progress.message}", file=sys.stderr)
    elif progress.status == "complete":
        print(f"\n{progress.message}", file=sys.stderr)


def process_single_file(
    audio_path: str, keywords: List[str], args: argparse.Namespace
) -> dict:
    """Process a single audio file."""
    if args.full:
        result = search_audio_full(
            audio_path, keywords, model_size=args.model, use_cache=not args.no_cache
        )
    else:
        result = search_audio(
            audio_path, keywords, model_size=args.model, use_cache=not args.no_cache
        )

    return result


def process_batch(
    audio_paths: List[str], keywords: List[str], args: argparse.Namespace
) -> dict:
    """Process multiple audio files."""
    results = {}

    if args.workers > 1:
        # Parallel processing
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_path = {
                executor.submit(process_single_file, path, keywords, args): path
                for path in audio_paths
            }

            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    results[path] = future.result()
                    if not args.quiet:
                        print(f"Completed: {path}", file=sys.stderr)
                except Exception as e:
                    results[path] = {"error": str(e)}
                    if not args.quiet:
                        print(f"Error processing {path}: {e}", file=sys.stderr)
    else:
        # Sequential processing
        for path in audio_paths:
            if not args.quiet:
                print(f"\nProcessing: {path}", file=sys.stderr)
            try:
                results[path] = process_single_file(path, keywords, args)
            except Exception as e:
                results[path] = {"error": str(e)}
                if not args.quiet:
                    print(f"Error: {e}", file=sys.stderr)

    return results


def cmd_search(args: argparse.Namespace):
    """Handle search command."""
    # Parse keywords
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if not keywords:
        print("Error: No keywords provided", file=sys.stderr)
        sys.exit(1)

    # Expand glob patterns for batch processing
    audio_paths = []
    for pattern in args.audio:
        expanded = glob.glob(pattern)
        if expanded:
            audio_paths.extend(expanded)
        elif os.path.exists(pattern):
            audio_paths.append(pattern)
        else:
            print(f"Warning: No files match '{pattern}'", file=sys.stderr)

    if not audio_paths:
        print("Error: No audio files found", file=sys.stderr)
        sys.exit(1)

    # Process info
    if not args.quiet:
        print(f"Audio files: {len(audio_paths)}", file=sys.stderr)
        print(f"Keywords: {keywords}", file=sys.stderr)
        print(f"Model: {args.model}", file=sys.stderr)
        print("", file=sys.stderr)

    # Process
    if len(audio_paths) == 1:
        # Single file - use streaming for live progress
        audio_path = audio_paths[0]

        if args.stream and not args.quiet:
            # Stream progress
            transcription = None
            for progress in transcribe_audio_streaming(
                audio_path, args.model, use_cache=not args.no_cache
            ):
                print_progress(progress, args.quiet)

            # Now search
            transcription = transcribe_audio(audio_path, args.model, use_cache=True)
            matches = find_keyword_matches(transcription["words"], keywords)

            # Group results
            if args.full:
                result = {
                    "text": transcription["text"],
                    "language": transcription["language"],
                    "duration": transcription["duration"],
                    "matches": matches,
                }
            else:
                result = {}
                for match in matches:
                    kw = match["keyword"]
                    if kw not in result:
                        result[kw] = []
                    result[kw].append(
                        {
                            "timestamp": match["timestamp"],
                            "timestamp_seconds": match["timestamp_seconds"],
                            "snippet": match["snippet"],
                        }
                    )
        else:
            result = process_single_file(audio_path, keywords, args)
            matches = []
            if args.full:
                matches = result.get("matches", [])
            else:
                for kw, kw_matches in result.items():
                    for m in kw_matches:
                        m["keyword"] = kw
                        matches.append(m)
    else:
        # Batch processing
        result = process_batch(audio_paths, keywords, args)
        matches = []  # Flat list for exports

        # Flatten matches from all files
        for path, file_result in result.items():
            if "error" not in file_result:
                if args.full:
                    for m in file_result.get("matches", []):
                        m["file"] = path
                        matches.append(m)
                else:
                    for kw, kw_matches in file_result.items():
                        for m in kw_matches:
                            m["keyword"] = kw
                            m["file"] = path
                            matches.append(m)

    # Export clips if requested
    if args.export_clips and matches:
        if not args.quiet:
            print(f"\nExporting clips to: {args.export_clips}", file=sys.stderr)

        audio_for_clips = audio_paths[0] if len(audio_paths) == 1 else None
        if audio_for_clips:
            clips = export_clips(
                audio_for_clips, matches, args.export_clips, padding=args.clip_padding
            )
            if not args.quiet:
                print(f"Exported {len(clips)} clips", file=sys.stderr)

    # Output
    if args.format == "json":
        output = json.dumps(result, indent=2)
    elif args.format in ("csv", "srt", "vtt", "markdown", "md"):
        output = export_matches(matches, args.format)
    else:
        output = json.dumps(result, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        _strip_quarantine(args.output)
        if not args.quiet:
            print(f"\nResults written to: {args.output}", file=sys.stderr)
    else:
        print(output)


def cmd_transcribe(args: argparse.Namespace):
    """Handle transcribe command (full transcription only)."""
    if not os.path.exists(args.audio):
        print(f"Error: File not found: {args.audio}", file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"Transcribing: {args.audio}", file=sys.stderr)
        print(f"Model: {args.model}", file=sys.stderr)

    # Stream transcription
    if args.stream and not args.quiet:
        for progress in transcribe_audio_streaming(
            args.audio, args.model, use_cache=not args.no_cache
        ):
            print_progress(progress, args.quiet)

    transcription = transcribe_audio(args.audio, args.model, use_cache=True)

    # Format output
    if args.format in ("srt", "vtt"):
        output = export_transcription(transcription["segments"], args.format)
    else:
        output = json.dumps(
            {
                "text": transcription["text"],
                "language": transcription["language"],
                "duration": transcription["duration"],
                "segments": transcription["segments"],
            },
            indent=2,
        )

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        _strip_quarantine(args.output)
        if not args.quiet:
            print(f"\nTranscription written to: {args.output}", file=sys.stderr)
    else:
        print(output)


def cmd_proximity(args: argparse.Namespace):
    """Handle proximity search command."""
    if not os.path.exists(args.audio):
        print(f"Error: File not found: {args.audio}", file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"Searching: {args.audio}", file=sys.stderr)
        print(
            f"Finding '{args.keyword1}' near '{args.keyword2}' (within {args.distance} words)",
            file=sys.stderr,
        )

    matches = search_audio_proximity(
        args.audio,
        args.keyword1,
        args.keyword2,
        max_distance=args.distance,
        model_size=args.model,
        use_cache=not args.no_cache,
    )

    # Output
    if args.format == "json":
        output = json.dumps(matches, indent=2)
    else:
        output = export_matches(matches, args.format)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        _strip_quarantine(args.output)
        if not args.quiet:
            print(f"\nResults written to: {args.output}", file=sys.stderr)
    else:
        print(output)


def cmd_memory(args: argparse.Namespace):
    """Handle memory management command."""
    if args.memory_action == "stats":
        stats = get_memory_stats()
        print(json.dumps(stats, indent=2))
    elif args.memory_action == "list":
        entries = list_memories()
        if not entries:
            print("No stored transcriptions.")
        else:
            print(f"Stored transcriptions ({len(entries)}):\n")
            for e in entries:
                print(f"  {e['title']}")
                print(
                    f"    Duration: {e['duration_formatted']} | Model: {e['model_size']} | Date: {e['date']}"
                )
                if e.get("md_path"):
                    print(f"    Markdown: {e['md_path']}")
                print()
    elif args.memory_action == "clear":
        count = clear_memory()
        print(f"Cleared {count} stored transcriptions")
    elif args.memory_action == "clear-models":
        clear_model_cache()
        print("Cleared model cache")
    elif args.memory_action == "search":
        query = args.search_query
        if not query:
            print("Error: search requires a query argument", file=sys.stderr)
            print('Usage: augent memory search "your query here"', file=sys.stderr)
            sys.exit(1)
        try:
            from .embeddings import search_memory
        except ImportError:
            print(
                "Error: sentence-transformers not installed. Install with: pip install sentence-transformers",
                file=sys.stderr,
            )
            sys.exit(1)
        mode = "semantic" if args.semantic else "keyword"
        result = search_memory(query, top_k=args.top_k, mode=mode)
        print(json.dumps(result, indent=2))


def cmd_setup(args: argparse.Namespace):
    """Handle setup command for platform integrations."""
    target = args.setup_target

    if target == "openclaw":
        _setup_openclaw()
    else:
        print(f"Unknown setup target: {target}", file=sys.stderr)
        print("Available targets: openclaw", file=sys.stderr)
        sys.exit(1)


def _setup_openclaw():
    """Configure augent as an OpenClaw skill with MCP integration."""
    import shutil

    # Resolve the SKILL.md source (bundled with augent package)
    skill_source = None
    package_dir = Path(__file__).parent.parent
    candidates = [
        package_dir / "openclaw" / "SKILL.md",
        Path(os.path.expanduser("~/.local/share/augent/openclaw/SKILL.md")),
    ]
    for candidate in candidates:
        if candidate.exists():
            skill_source = candidate
            break

    # Detect OpenClaw installation
    has_openclaw = (
        Path(os.path.expanduser("~/.openclaw")).exists()
        or shutil.which("openclaw") is not None
    )

    # Detect Python path for MCP command
    python_abs = sys.executable
    mcp_cmd = shutil.which("augent-mcp")

    print()
    print("  Augent — OpenClaw Setup")
    print("  " + "=" * 40)
    print()

    # Step 1: Install SKILL.md
    skill_dir = Path(os.path.expanduser("~/.openclaw/skills/augent"))
    skill_dest = skill_dir / "SKILL.md"

    if skill_source:
        skill_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_source, skill_dest)
        print(f"  \033[32m✓\033[0m Skill installed to {skill_dest}")
    else:
        # Generate SKILL.md inline if source not found
        skill_dir.mkdir(parents=True, exist_ok=True)
        _write_skill_md(skill_dest, mcp_cmd, python_abs)
        print(f"  \033[32m✓\033[0m Skill generated at {skill_dest}")

    # Step 2: Configure MCP in OpenClaw config
    openclaw_config = Path(os.path.expanduser("~/.openclaw/openclaw.json"))
    _configure_openclaw_mcp(openclaw_config, mcp_cmd, python_abs)

    # Step 3: Print summary
    print()
    if has_openclaw:
        print("  \033[32m✓\033[0m OpenClaw detected")
    else:
        print(
            "  \033[33m!\033[0m OpenClaw not detected — skill files installed for when you set it up"
        )

    print()
    print("  \033[1mWhat was configured:\033[0m")
    print(f"  Skill:  {skill_dest}")
    print(f"  Config: {openclaw_config}")
    print()
    print("  \033[1mMCP server:\033[0m")
    if mcp_cmd:
        print(f"  Command: {mcp_cmd}")
    else:
        print(f"  Command: {python_abs} -m augent.mcp")
    print()
    print("  \033[33mNext step:\033[0m Restart OpenClaw to load the augent skill")
    print()


def _configure_openclaw_mcp(config_path: Path, mcp_cmd: Optional[str], python_abs: str):
    """Add augent MCP server to OpenClaw's config."""
    import json as json_mod

    config = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json_mod.load(f)
        except (json_mod.JSONDecodeError, OSError):
            config = {}

    # Build MCP server entry
    if mcp_cmd:
        server_entry = {"command": mcp_cmd}
    else:
        server_entry = {"command": python_abs, "args": ["-m", "augent.mcp"]}

    # Add to mcpServers
    if "mcpServers" not in config:
        config["mcpServers"] = {}
    config["mcpServers"]["augent"] = server_entry

    # Write config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json_mod.dump(config, f, indent=2)
        f.write("\n")

    print(f"  \033[32m✓\033[0m MCP server added to {config_path}")


def _write_skill_md(dest: Path, mcp_cmd: Optional[str], python_abs: str):
    """Generate SKILL.md when the bundled file isn't available."""
    if mcp_cmd:
        config_json = '        "command": "augent-mcp"'
    else:
        config_json = (
            f'        "command": "{python_abs}",\n        "args": ["-m", "augent.mcp"]'
        )

    content = f"""---
name: augent
description: Audio intelligence toolkit. Transcribe, search, take notes, detect chapters, identify speakers, separate audio, export clips, tag, highlights, visual context, and text-to-speech — all local, all private. 21 MCP tools for audio and video.
homepage: https://github.com/AugentDevs/Augent
metadata: {{"openclaw":{{"emoji":"🎙","os":["darwin","linux","win32"],"requires":{{"bins":["augent-mcp","ffmpeg"]}},"install":[{{"id":"uv","kind":"uv","package":"augent","bins":["augent-mcp","augent","augent-web"],"label":"Install augent (uv)"}},{{"id":"pip","kind":"pip","package":"augent[all]","bins":["augent-mcp","augent","augent-web"],"label":"Install augent (pip)"}}]}}}}
---

# Augent — Audio Intelligence for AI Agents

21 MCP tools for audio and video: transcribe, search, take notes, identify speakers, detect chapters, separate audio, export clips, tag, highlights, visual context, and text-to-speech. Fully local, fully private.

## Config

```json
{{
  "mcpServers": {{
    "augent": {{
{config_json}
    }}
  }}
}}
```

## Install

```bash
curl -fsSL https://augent.app/install.sh | bash
```

## Tools

download_audio, transcribe_audio, search_audio, deep_search, search_memory, take_notes, clip_export, chapters, search_proximity, identify_speakers, separate_audio, batch_search, text_to_speech, tag, highlights, rebuild_graph, list_files, list_memories, memory_stats, clear_memory

## Links

- [GitHub](https://github.com/AugentDevs/Augent)
- [Documentation](https://docs.augent.app)
"""
    with open(dest, "w") as f:
        f.write(content)


def cmd_help(args: argparse.Namespace):
    """Show detailed help and quick start guide."""
    from .banner import render_banner

    try:
        import importlib.metadata

        version = importlib.metadata.version("augent")
    except Exception:
        version = "2026.2.28"

    help_text = f"""
{render_banner('AUGENT')}
  AUGENT v{version} — Audio Intelligence Tool

QUICK START
-----------
  Install:    curl -fsSL https://augent.app/install.sh | bash
  Run Web UI: augent-web
  Open:       http://127.0.0.1:8282

COMMANDS
--------
  augent search <file> "keywords"       Search audio for keywords
  augent transcribe <file>              Full transcription
  augent proximity <file> "A" "B"       Find keyword A near keyword B
  augent memory stats                   View memory statistics
  augent memory list                    List stored transcriptions by title
  augent memory search "query"          Search across all stored transcriptions
  augent memory clear                   Clear transcription memory
  augent memory clear-models            Clear downloaded Whisper models
  augent setup openclaw                 Configure augent for OpenClaw

OPTIONS
-------
  --model, -m <size>                    Whisper model (tiny | base | small | medium | large)
  --format <fmt>                        Output format (json | csv | srt | vtt | markdown)
  --output, -o <file>                   Write results to file
  --workers, -w <n>                     Parallel workers for batch processing
  --export-clips <dir>                  Extract audio clips around keyword matches
  --clip-padding <sec>                  Seconds before/after each clip (default: 15)
  --no-cache                            Skip transcription cache
  --stream                              Stream progress to stderr

OTHER TOOLS
-----------
  audio-downloader "URL"                Download audio from any video URL
  audio-downloader url1 url2 url3       Download multiple URLs
  augent-web                            Launch Web UI (http://127.0.0.1:8282)
  augent-mcp                            Start MCP server for Claude Code

EXAMPLES
--------
  # Download and transcribe
  audio-downloader "https://youtube.com/watch?v=xxx"
  augent transcribe ~/Downloads/podcast.webm

  # Search for keywords
  augent search podcast.mp3 "lucrative,funding,healthiest"

  # Batch process with parallel workers
  augent search "*.mp3" "keyword" --workers 4

  # Export to CSV or SRT
  augent search audio.mp3 "keyword" --format csv -o results.csv
  augent transcribe audio.mp3 --format srt -o subtitles.srt

  # Extract audio clips around keyword matches
  augent search audio.mp3 "important" --export-clips ./clips

  # Proximity search
  augent proximity audio.mp3 "problem" "solution" --distance 30

  # Search across all stored transcriptions
  augent memory search "sea moss"

MODEL SIZES
-----------
  tiny     Fastest, great accuracy (default)
  base     Fast, excellent accuracy
  small    Medium speed, superior accuracy
  medium   Slow, outstanding accuracy
  large    Slowest, maximum accuracy

INSTALLED BY THE ONE-LINER
--------------------------
  Python 3.10+ | FFmpeg | yt-dlp + aria2

Docs:   https://docs.augent.app
GitHub: https://github.com/AugentDevs/Augent
================================================================================
"""
    print(help_text)


def print_simple_help():
    """Print clean, simple help."""
    from .banner import render_banner

    try:
        import importlib.metadata

        version = importlib.metadata.version("augent")
    except Exception:
        version = "2026.2.28"

    help_text = f"""
{render_banner('AUGENT')}

  augent v{version}
  Audio intelligence for AI agents.

Usage:
  augent <command> [options]

Commands:
  search <file> "keywords"         Search audio, export clips
  transcribe <file>                Full transcription
  proximity <file> "A" "B"         Find two keywords near each other
  memory stats                     View memory statistics
  memory list                      List stored transcriptions
  memory search "query"            Search across all transcriptions
  memory clear                     Clear transcription memory
  memory clear-models              Remove downloaded Whisper models
  setup openclaw                   Configure augent for OpenClaw

Related Tools:
  augent-web                       Launch the web UI
  augent-mcp                       Start the MCP server
  audio-downloader "URL"           Download audio from any URL

Global Options:
  -m, --model <size>               Whisper model: tiny, base, small, medium, large
  -f, --format <fmt>               Output: json, csv, srt, vtt, markdown
  -o, --output <file>              Write results to file
  -w, --workers <n>                Parallel workers for batch processing
  --no-cache                       Skip transcription cache

Examples:
  augent search podcast.mp3 "AI,automation"
  augent search "*.mp3" "keyword" -w 4 --format csv
  augent transcribe lecture.mp3 --format srt -o subtitles.srt
  augent proximity interview.mp3 "problem" "solution" -d 30

Run 'augent help' for the full reference.
https://docs.augent.app
"""
    print(help_text)


def main():
    # Handle --help and -h with clean output
    if len(sys.argv) == 1 or sys.argv[1] in ("--help", "-h"):
        print_simple_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Augent - Audio intelligence for agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,  # We handle help ourselves
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search audio for keywords")
    search_parser.add_argument(
        "audio", nargs="+", help="Audio file(s) or glob pattern (e.g., '*.mp3')"
    )
    search_parser.add_argument(
        "keywords", help="Comma-separated keywords to search for"
    )
    search_parser.add_argument(
        "--model",
        "-m",
        default="tiny",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: tiny)",
    )
    search_parser.add_argument(
        "--full", "-f", action="store_true", help="Include full transcription in output"
    )
    search_parser.add_argument(
        "--format",
        default="json",
        choices=["json", "csv", "srt", "vtt", "markdown", "md"],
        help="Output format (default: json)",
    )
    search_parser.add_argument("--output", "-o", help="Write output to file")
    search_parser.add_argument(
        "--export-clips",
        metavar="DIR",
        help="Export audio clips around matches to directory",
    )
    search_parser.add_argument(
        "--clip-padding",
        type=float,
        default=15.0,
        help="Seconds of audio before/after each clip (default: 15)",
    )
    search_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=1,
        help="Parallel workers for batch processing (default: 1)",
    )
    search_parser.add_argument(
        "--stream",
        "-s",
        action="store_true",
        help="Stream transcription progress to stderr",
    )
    search_parser.add_argument(
        "--no-cache", action="store_true", help="Disable transcription caching"
    )
    search_parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress progress messages"
    )

    # Transcribe command
    transcribe_parser = subparsers.add_parser(
        "transcribe", help="Transcribe audio without keyword search"
    )
    transcribe_parser.add_argument("audio", help="Audio file to transcribe")
    transcribe_parser.add_argument(
        "--model",
        "-m",
        default="tiny",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: tiny)",
    )
    transcribe_parser.add_argument(
        "--format",
        default="json",
        choices=["json", "srt", "vtt"],
        help="Output format (default: json)",
    )
    transcribe_parser.add_argument("--output", "-o", help="Write output to file")
    transcribe_parser.add_argument(
        "--stream", "-s", action="store_true", help="Stream transcription progress"
    )
    transcribe_parser.add_argument(
        "--no-cache", action="store_true", help="Disable caching"
    )
    transcribe_parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress progress messages"
    )

    # Proximity command
    proximity_parser = subparsers.add_parser(
        "proximity", help="Find keyword1 near keyword2"
    )
    proximity_parser.add_argument("audio", help="Audio file to search")
    proximity_parser.add_argument("keyword1", help="Primary keyword")
    proximity_parser.add_argument("keyword2", help="Must appear nearby")
    proximity_parser.add_argument(
        "--distance",
        "-d",
        type=int,
        default=30,
        help="Max words allowed between keyword1 and keyword2 (default: 30)",
    )
    proximity_parser.add_argument(
        "--model",
        "-m",
        default="tiny",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: tiny)",
    )
    proximity_parser.add_argument(
        "--format",
        default="json",
        choices=["json", "csv", "markdown"],
        help="Output format (default: json)",
    )
    proximity_parser.add_argument("--output", "-o", help="Write output to file")
    proximity_parser.add_argument(
        "--no-cache", action="store_true", help="Disable caching"
    )
    proximity_parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress progress messages"
    )

    # Memory command
    memory_parser = subparsers.add_parser("memory", help="Manage transcription memory")
    memory_parser.add_argument(
        "memory_action",
        choices=["stats", "list", "clear", "clear-models", "search"],
        help="Memory action",
    )
    memory_parser.add_argument(
        "search_query", nargs="?", help="Search query (required for 'search' action)"
    )
    memory_parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=10,
        help="Number of results for search (default: 10)",
    )
    memory_parser.add_argument(
        "--semantic",
        action="store_true",
        help="Use semantic (meaning-based) search instead of keyword matching",
    )

    # Setup command
    setup_parser = subparsers.add_parser(
        "setup", help="Configure augent for a platform"
    )
    setup_parser.add_argument(
        "setup_target", choices=["openclaw"], help="Platform to configure (openclaw)"
    )

    # Help command
    subparsers.add_parser("help", help="Show detailed help and quick start guide")

    # Parse and dispatch
    args = parser.parse_args()

    if args.command is None:
        # Default to search if positional args provided (backwards compatibility)
        parser.print_help()
        sys.exit(0)

    try:
        if args.command == "search":
            cmd_search(args)
        elif args.command == "transcribe":
            cmd_transcribe(args)
        elif args.command == "proximity":
            cmd_proximity(args)
        elif args.command == "memory":
            cmd_memory(args)
        elif args.command == "setup":
            cmd_setup(args)
        elif args.command == "help":
            cmd_help(args)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
