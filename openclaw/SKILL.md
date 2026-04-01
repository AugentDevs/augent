---
name: augent
description: The audio & video layer for agents. 22 local MCP tools. No cloud, no API keys.
homepage: https://github.com/AugentDevs/Augent
metadata: {"openclaw":{"emoji":"🎙","os":["darwin","linux","win32"],"requires":{"bins":["augent-mcp","ffmpeg"]},"install":[{"id":"uv","kind":"uv","package":"augent","bins":["augent-mcp","augent","augent-web"],"label":"Install augent (uv)"},{"id":"pip","kind":"pip","package":"augent[all]","bins":["augent-mcp","augent","augent-web"],"label":"Install augent (pip)"}]}}
---

# Augent — Audio & Video Intelligence for AI Agents

Augent is an MCP server that gives your agent 22 tools for audio and video intelligence. Download from 1000+ sites, transcribe in 99 languages, search by keyword or meaning, take notes, identify speakers, detect chapters, separate audio, export clips, extract visual frames, record X/Twitter Spaces, and generate speech. All processing runs locally on your machine. Network access is used only for downloading media from URLs. Filesystem access is used for storing transcriptions, notes, and clips locally.

## Config

```json
{
  "mcpServers": {
    "augent": {
      "command": "augent-mcp"
    }
  }
}
```

If `augent-mcp` is not in PATH, use `python3 -m augent.mcp` as the command instead.

## Install

Install via the ClawHub install button above, or use `uv tool install augent` for the base package or `uv tool install "augent[all]"` for all features. FFmpeg is required for audio processing.

## Tools

Augent exposes 22 MCP tools:

### Core

| Tool | Description |
|------|-------------|
| `download_audio` | Download audio from video URLs at maximum speed. Supports YouTube, Vimeo, TikTok, Twitter/X, SoundCloud, and 1000+ sites. Uses aria2c multi-connection + concurrent fragments. |
| `transcribe_audio` | Full transcription of any audio file with per-segment timestamps. Returns text, language, duration, and segments. Cached by file hash. |
| `search_audio` | Search audio for keywords. Returns timestamped matches with context snippets. Supports clip export. |
| `deep_search` | Semantic search — find moments by meaning, not just keywords. Uses sentence-transformers embeddings. |
| `search_memory` | Search across ALL stored transcriptions in one query. Keyword or semantic mode. |
| `take_notes` | All-in-one: download audio from URL, transcribe, and save formatted notes. Supports 5 styles: tldr, notes, highlight, eye-candy, quiz. |
| `clip_export` | Export a video clip from any URL for a specific time range. Downloads only the requested segment. |

### Analysis

| Tool | Description |
|------|-------------|
| `chapters` | Auto-detect topic chapters with timestamps using embedding similarity. |
| `search_proximity` | Find where two keywords appear near each other (e.g., "startup" within 30 words of "funding"). |
| `identify_speakers` | Speaker diarization — identify who speaks when. No API keys required. |
| `separate_audio` | Isolate vocals from music/noise using Meta's Demucs v4. Feed clean vocals into transcription. |
| `batch_search` | Search multiple audio files in parallel. Ideal for podcast libraries or interview collections. |

### Utilities

| Tool | Description |
|------|-------------|
| `text_to_speech` | Convert text to natural speech using Kokoro TTS. 54 voices, 9 languages. Runs in background. |
| `list_files` | List media files in a directory with size info. |
| `list_memories` | Browse all stored transcriptions by title, duration, and date. |
| `memory_stats` | View memory statistics (file count, total duration). |
| `clear_memory` | Clear the transcription memory to free disk space. |
| `tag` | Add, remove, or list tags on transcriptions. Broad topic categories for organizing memories. |
| `highlights` | Export the best moments from a transcription. Auto mode picks top moments; focused mode finds moments matching a topic. |
| `visual` | Extract visual context from video at moments that matter. Query, auto, manual, and assist modes. Frames saved to Obsidian vault. |
| `rebuild_graph` | Rebuild Obsidian graph view data for all transcriptions. Migrates files, computes wikilinks, generates MOC hubs. |
| `spaces` | Download or live-record X/Twitter Spaces. Start, check status, or stop recordings. |

## Usage Examples

### Take notes from a video

> "Take notes from https://youtube.com/watch?v=xxx"

The agent calls `take_notes` which downloads, transcribes, and returns formatted notes. One tool call does everything.

### Search a podcast for topics

> "Search this podcast for every mention of AI regulation" — provide the file path or URL.

The agent uses `search_audio` for exact keyword matches, or `deep_search` for semantic matches (finds relevant discussion even without exact words).

### Transcribe and identify speakers

> "Transcribe this meeting recording and tell me who said what"

The agent calls `transcribe_audio` then `identify_speakers` to label each segment by speaker.

### Search across all transcriptions

> "Search everything I've ever transcribed for mentions of funding"

The agent uses `search_memory` to search across all stored transcriptions without needing a file path.

### Export a clip

> "Clip the part where they talk about pricing"

The agent uses `search_audio` or `deep_search` to find the moment, then `clip_export` to extract just that segment.

### Separate vocals from noisy audio

> "This recording has music in the background, clean it up and transcribe"

The agent calls `separate_audio` to isolate vocals, then `transcribe_audio` on the clean vocals track.

### Generate speech from text

> "Read these notes aloud"

The agent calls `text_to_speech` to generate an MP3 with natural speech. Supports multiple voices and languages.

## Note Styles

When using `take_notes`, the `style` parameter controls formatting:

| Style | Description |
|-------|-------------|
| `tldr` | Shortest possible summary. One screen. Bold key terms. |
| `notes` | Clean sections with nested bullets (default). |
| `highlight` | Notes with callout blocks for key insights and blockquotes with timestamps. |
| `eye-candy` | Maximum visual formatting — callouts, tables, checklists, blockquotes. |
| `quiz` | Multiple-choice questions with answer key. |

## Model Sizes

`tiny` is the default and handles nearly everything. Only use larger models for heavy accents, poor audio quality, or maximum accuracy needs.

| Model | Speed | Accuracy |
|-------|-------|----------|
| **tiny** | Fastest | Excellent (default) |
| base | Fast | Excellent |
| small | Medium | Superior |
| medium | Slow | Outstanding |
| large | Slowest | Maximum |

## Memory

Transcriptions are stored by file content hash + model size. Same file = instant results on repeat searches. Memory persists at `~/.augent/memory/transcriptions.db`. Source URLs from any platform are permanently stored by file hash. Use `memory_stats` to check usage and `clear_memory` to free space.

## Requirements

- Python 3.10+
- FFmpeg (audio processing)
- yt-dlp + aria2 (optional, for audio downloads)

## Links

- [GitHub](https://github.com/AugentDevs/Augent)
- [Documentation](https://docs.augent.app)
