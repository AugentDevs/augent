# Augent — The Audio Layer for Agents

<p align="center">
  <picture>
    <img src="./images/logo.png" width="600" alt="Augent">
  </picture>
</p>

<p align="center">
  <strong>Any amount of content, seconds to find it. Fully local, fully private.</strong>
</p>

<p align="center">
  <a href="https://github.com/AugentDevs/Augent/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/AugentDevs/Augent/tests.yml?label=build&style=for-the-badge" alt="Build"></a>
  <img src="https://img.shields.io/badge/dynamic/toml?url=https://raw.githubusercontent.com/AugentDevs/Augent/main/pyproject.toml&query=$.project.version&label=version&style=for-the-badge" alt="Version">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-3776AB.svg?style=for-the-badge" alt="Python 3.10+"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#mcp-tools">MCP Tools</a> ·
  <a href="#cli">CLI</a> ·
  <a href="#web-ui">Web UI</a> ·
  <a href="https://docs.augent.app">Docs</a>
</p>

**Augent** turns any audio or video source into structured, searchable intelligence for agents. Give it URLs or files. It downloads, transcribes, indexes, and stores everything in persistent memory. Search by keyword or meaning, find where concepts intersect, identify speakers, generate chapters and notes, batch process entire libraries, and more. One install, full pipeline, entirely on your machine.

**Preferred setup:** run the one-line installer in your terminal. It installs everything automatically — Augent, dependencies, and the MCP server config. Works on macOS and Linux. Windows: install via pip. Works with Claude Code, Codex, and any MCP client. New install? Start here: [Getting started](https://docs.augent.app/getting-started).

[Website](https://augent.app) · [Tool Reference](https://docs.augent.app/tools/download-audio) · [Changelog](CHANGELOG.md)

<br />

## Install

```bash
curl -fsSL https://augent.app/install.sh | bash
```

Works on macOS and Linux. Installs everything automatically.

**Windows:** `pip install "augent[all] @ git+https://github.com/AugentDevs/Augent.git"`

<br />

<p align="center">
  <picture>
    <img src="./images/install-demo.svg" alt="Install demo">
  </picture>
</p>

<br />

## How It Works

```mermaid
%%{init: {'theme': 'dark'}}%%
flowchart LR
    A["URL / File"] --> B["Download"]
    B --> C["Transcribe"]
    C --> D["Memory"]
    D --> E["Search"]
    D --> F["Analyze"]
    D --> G["Export"]

    E --> E1["Keyword"]
    E --> E2["Semantic"]
    E --> E3["Batch"]
    E --> E4["Proximity"]
    E --> E5["Cross-Memory"]

    F --> F1["Speaker ID"]
    F --> F2["Chapters"]
    F --> F3["Notes"]

    G --> G1["Text to Speech"]
```

## Project Structure

```
augent/
├── mcp.py          # MCP server — tools for agents
├── core.py         # Transcription engine (faster-whisper)
├── search.py       # Keyword search
├── embeddings.py   # Semantic search + chapters
├── speakers.py     # Speaker diarization
├── tts.py          # Text-to-speech (Kokoro)
├── memory.py       # Three-layer memory (SQLite)
├── cli.py          # CLI interface
├── web.py          # Web UI (Gradio)
├── export.py       # Export formats (JSON, CSV, SRT, VTT, MD)
└── clips.py        # Audio clip extraction
```

<br />

## MCP Tools

The primary way to use Augent. Any MCP client gets direct access to all tools.

Add to `~/.claude.json` (global) or `.mcp.json` (project):

```json
{
  "mcpServers": {
    "augent": {
      "command": "augent-mcp"
    }
  }
}
```

Restart Claude Code. Run `/mcp` to verify connection.

| Tool | Description |
|:-----|:------------|
| `download_audio` | Download audio from video URLs at maximum speed (1,000+ supported sites) |
| `transcribe_audio` | Full transcription with metadata |
| `search_audio` | Find keywords with timestamps and context snippets |
| `deep_search` | Search audio by meaning, not just keywords (semantic search) |
| `take_notes` | Take notes from any URL with style presets |
| `chapters` | Auto-detect topic chapters in audio with timestamps |
| `batch_search` | Search multiple files in parallel — built for batch workflows and agent swarms |
| `text_to_speech` | Convert text to natural speech audio (Kokoro TTS, 54 voices, 9 languages) |
| `search_proximity` | Find where keywords appear near each other |
| `identify_speakers` | Identify who speaks when in audio (speaker diarization) |
| `search_memory` | Search across ALL stored transcriptions by keyword or meaning |
| `list_files` | List media files in a directory |
| `list_memories` | List stored transcriptions by title |
| `memory_stats` | View transcription memory statistics |
| `clear_memory` | Clear stored transcriptions |

**[Full tool reference →](https://docs.augent.app/tools/download-audio)**

<details>
<summary>Example prompt</summary>

> *"Download these 10 podcasts and find every moment a host covers a product in a positive or unique way. Not just brand mentions, only real endorsements or life-changing recommendations. Give me the timestamps and exactly what they said: url1, url2, url3, url4, url5, url6, url7, url8, url9, url10"*

<p align="center">
  <picture>
    <img src="./images/pipeline.png" alt="Augent Pipeline — From URLs to insights in one prompt" width="100%">
  </picture>
</p>

</details>

<br />

## CLI

Full CLI for terminal-based workflows. Works standalone or with any agent.

<picture>
  <img src="./images/cli-help.png" alt="Augent CLI">
</picture>

| Command | Description |
|:--------|:------------|
| `audio-downloader "URL"` | Download audio from video URL (speed-optimized) |
| `augent search audio.mp3 "keyword"` | Search for keywords |
| `augent transcribe audio.mp3` | Full transcription |
| `augent proximity audio.mp3 "A" "B"` | Find keyword A near keyword B |
| `augent memory search "query"` | Search across all stored transcriptions |
| `augent memory stats` | View memory statistics |
| `augent memory list` | List stored transcriptions |
| `augent memory clear` | Clear memory |

<br />

## Web UI

Local web interface. Runs 100% locally — no internet, no API keys, no data leaves your machine.

```bash
python3 -m augent.web
```

Open: **http://127.0.0.1:9797**

1. **Upload** an audio file (MP3, WAV, M4A, etc.)
2. **Enter keywords** separated by commas
3. **Click SEARCH**
4. **View results** with timestamps and context

<details>
<summary>Web UI options</summary>

| Command | Description |
|:--------|:------------|
| `python3 -m augent.web` | Start on port 9797 |
| `python3 -m augent.web --port 3000` | Custom port |
| `python3 -m augent.web --share` | Create public link |

</details>

<picture>
  <img src="./images/webui-1.png" alt="Augent Web UI - Upload">
</picture>
<picture>
  <img src="./images/webui-2.png" alt="Augent Web UI - Results">
</picture>

<br />

## Model Sizes

**`tiny` is the default.** Handles everything from clean studio recordings to noisy field audio. Use `small` or above for heavy accents, poor audio, or lyrics.

| Model | Speed | Accuracy |
|:------|:------|:---------|
| **tiny** | Fastest | Excellent (default) |
| base | Fast | Excellent |
| small | Medium | Superior |
| medium | Slow | Outstanding |
| large | Slowest | Maximum |

<br />

## Contributing

PRs welcome. Open an [issue](https://github.com/AugentDevs/Augent/issues) for bugs or feature requests.

<br />

## License

MIT
