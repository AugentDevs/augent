# Changelog

All notable changes to Augent are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/).

## [2026.3.22] - 2026-03-22

### Added

- **Obsidian graph view integration:** all memory `.md` files now include YAML frontmatter (`title`, `tags`, `source_url`, `duration`, `language`, `date`, `type`) for full Obsidian graph view support. Tags appear as hub nodes, [[wikilinks]] connect semantically related transcriptions, and MOC (Map of Content) files cluster topics.
- **`rebuild_graph` MCP tool:** one-shot command to migrate existing memory files to YAML frontmatter, compute related [[wikilinks]] via embedding similarity, and generate MOC hub files for tag clusters. Safe to run repeatedly.
- **MOC (Map of Content) auto-generation:** tags with 3+ members automatically get a hub `.md` file linking all their transcriptions — creates visible topic clusters in the graph.
- **Semantic related links:** transcriptions with similar content are connected via [[wikilinks]] in a `## Related` section, computed from document-level embedding cosine similarity + shared tag bonus.
- **`augent/graph.py` module:** new module for all Obsidian graph operations — related links, MOC generation, markdown migration, and full graph rebuild.

### Changed

- **`take_notes` output switched from `.txt` to `.md`:** notes files now use `.md` extension with auto-generated YAML frontmatter (`type: notes`, `source_transcription` wikilink, inherited tags, style). No manual frontmatter needed — it's prepended automatically in the `save_content` handler.
- **Tag changes sync to `.md` frontmatter:** `add_tags` and `remove_tags` now update the YAML frontmatter in the corresponding `.md` file in real time. Tags exist in both the DB (source of truth) and the file (Obsidian-facing).
- **Translation files include frontmatter:** translated `.md` files now have YAML frontmatter with `type: translation` and `original: [[source_file]]` wikilink back to the original transcription.
- **Memory `.md` files restructured:** header metadata moved from bold text (`**Duration:** 9:47`) into YAML frontmatter. Body starts with `# Title` followed by `## Transcription`.

## [2026.3.21] - 2026-03-21

### Added

- **User configuration (`~/.augent/config.yaml`):** set defaults for model_size, output_dir, notes_output_dir, clip_padding, context_words, tts_voice, and tts_speed. Per-call arguments always override config values. Falls back to `~/.augent/config.json` if PyYAML is not installed. No config file required — all values have sensible defaults.
- **`disabled_tools` config key:** list tool names to hide from MCP clients. Disabled tools are removed from the `tools/list` response and cannot be called.

## [2026.3.20] - 2026-03-20

### Added

- **`tag` MCP tool:** add, remove, or list tags on any transcription. Tags are broad topic categories (e.g. "AI", "Health", "Gaming") for organizing and filtering memories.
- **Semantic tagging:** new transcriptions are automatically tagged using sentence-transformer embeddings. Compares content against existing tagged transcriptions to assign matching tags — works on both Web UI and MCP flows, no LLM required.
- **Web UI tag filter bar:** clickable tag pills above the Memory list. Click a tag to filter transcriptions by topic. Tag counts shown inline.
- **Web UI tag pills on memory cards:** each memory card displays up to 5 tag pills for at-a-glance topic identification.
- **Tags API:** `GET /api/memory/tags` returns all tags with usage counts.

### Changed

- **Highlights clip padding default:** increased from 5s to 10s — more context for the user to trim rather than missing content.
- **Highlights and deep_search clip export:** clips now use full time ranges (start → end) instead of just a single timestamp with symmetric padding. A 45-second highlight now produces a ~65s clip, not a 10s clip around the start point.
- **`_build_snippet` expanded boundaries:** snippet text and timestamps now cover the full range of segments used, not just the center segment.
- **MCP tagging flow:** `transcribe_audio` and `take_notes` responses include existing tag library in the tagging hint, so Claude reuses existing categories instead of creating duplicates.

### Removed

- **Regex auto-tagger:** replaced by semantic tagging. The old approach extracted every repeated capitalized word (producing junk like "Greg", "Markdown", "Code" as tags).

---

## [2026.3.19] - 2026-03-19

### Added

- **`highlights` MCP tool:** export MP4 clips of specific moments, auto-pick the best or target exactly what you want. Two modes: auto (AI picks top moments by content density) or focused (find moments matching a specific topic, person, or concept). Supports optional clip export with configurable padding.
- **Auto-tagging:** transcriptions created via `take_notes` now automatically extract and store tags for faster discovery.
- **`search_audio` and `deep_search` clip export:** both tools now support `clip` and `clip_padding` parameters to export MP4 clips around keyword matches.
- **Highlights tests:** added tests for highlights tool and auto-tagging pipeline.
- **Expanded multilingual support:** multilingual section updated with 99 supported languages.

### Changed

- **Tool descriptions:** "extract" → "export" across highlights tool descriptions for consistency. Em dashes replaced with commas in tool table descriptions.
- **CI dependency bumps:** `actions/labeler` v5 → v6, `actions/stale` v9 → v10, `actions/checkout` v4 → v6, `actions/setup-python` v5 → v6, `huggingface-hub` upper bound → <1.8.0.

### Fixed

- **CodeQL security fix:** validated clip reveal path against tracked clips to prevent path traversal.
- **`take_notes` from memory:** new `output_path` parameter allows saving notes from memory transcripts without requiring a URL.
- **Black formatting:** reformatted all modified files to pass CI.
- **Ruff lint:** removed unused variables in tests and handlers.

---

## [2026.3.15] - 2026-03-15

### Added

- **Web UI visual clip export:** click the film icon on any search result to create a region on the waveform, or drag-select any range manually. A clip toolbar appears below the waveform with ±1s/±5s nudge buttons for precise boundary adjustment, a preview button to hear exactly what will be exported, and an Export MP4 button.
- **WaveSurfer Regions plugin:** interactive regions on the audio waveform with draggable edges and body repositioning. Only one clip region active at a time.
- **Expanded Web UI tips:** 8 tips (up from 3) covering clip export workflow, Memory tab re-search, parallel tabs, YouTube timestamps, and cross-memory search.

---

## [2026.3.12] - 2026-03-12

### Added

- **`clip_export` MCP tool:** export a video clip from any URL for a specific time range. Downloads only the requested segment — not the full video. Supports YouTube, Instagram, TikTok, Twitter/X, and 1000+ sites via yt-dlp.
- **Multilingual translation flow:** when `transcribe_audio` or `take_notes` detects non-English audio, a translation offer is returned. Accepting stores a clean English `(eng)` sibling file in memory alongside the original transcription.
- **Web UI "Show Transcript" button:** new document icon on memory cards reveals the `.md` transcript file in Finder, separate from the audio file reveal.
- **Web UI "Show Audio" / "Show Transcript" in detail view:** two distinct buttons to reveal either the audio source or the transcript file.
- **Web UI re-search from memory:** search a previously transcribed file again without re-uploading.

### Changed

- **Download filenames now include video ID:** `%(title)s [%(id)s].%(ext)s` prevents overwrites when multiple videos share the same title (e.g., multiple Instagram reels from the same account).
- **Download filenames sanitized to ASCII:** `--restrict-filenames` replaces Unicode characters (smart quotes, accented characters, etc.) with safe ASCII equivalents, preventing broken file paths in downstream tools.
- **Translation `(eng)` files are now clean English text:** no timestamps, no per-segment mapping — just the full translated text with metadata header. Previously, the line-to-segment mapping produced broken files mixing English and original language.
- **Translation offer moved to `transcribe_audio` level:** works for any transcription call, not just `take_notes`. Removed fragile global state (`_last_translation_offer`, `_last_audio_path`).
- **Clip export now overwrites existing files:** `--force-overwrites` ensures re-exporting a clip with different padding replaces the previous file instead of silently skipping.
- **Default clip padding increased to 15 seconds:** up from 10s (MCP) and 5s (CLI) for better context around keyword matches.
- **Web UI default port changed to 8282:** moved from 9797 to avoid the crowded 9000s range.

### Fixed

- **CI workflow auth failures:** downgraded `actions/checkout@v6` → `@v4` and `actions/setup-python@v6` → `@v5`; added explicit `permissions: contents: read` to Tests workflow.
- **Test count mismatch:** updated expected tool count from 16 → 17 after `clip_export` was added.
- **Ruff lint errors:** removed f-strings without placeholders, unused `label` variable, `dict()` calls.
- **Black formatting:** reformatted all modified files to pass CI.
- **Handler test coverage:** added 59 tests for `download_audio`, `clip_export`, `transcribe_audio`, `chapters`, `batch_search`, and `separate_audio` — covering command construction, flag verification, parameter defaults, and error handling.

---

## [2026.3.11] - 2026-03-11

### Added

- **Web UI waveform for URL downloads:** downloading audio from a URL now renders an interactive waveform with full playback controls (play/pause, skip to start/end, volume slider) — same experience as file uploads
- **Web UI download spinner:** animated wormhole spinner replaces the progress bar during audio downloads for a cleaner look
- **Web UI transcription progress bar:** real-time progress bar shown in the results panel during transcription
- **Web UI Show in Finder button:** folder icon on memory cards to reveal the audio file (or `.md` fallback) in Finder
- **Web UI URL-based memory caching:** pasting the same URL again skips re-downloading — instant cache hit by source URL + model size

### Changed

- **Web UI memory stats:** transcription count and placeholder text are now larger and use the green accent color for better readability
- **Web UI keyword placeholder:** updated to "wormhole, open source, workflow"
- **Web UI progress/spinner location:** moved from the log box to the results panel where it's more visible

### Fixed

- **`augent-web` startup:** server no longer silently exits on launch; prints a clean "WebUI is live at" message
- **`_kill_port` killing own process:** added PID check so the server doesn't terminate itself on startup
- **Memory not saving from Web UI downloads:** macOS `tempfile.mkdtemp()` created dirs in `/var/folders/` which failed the `/tmp` security check — now forces `/tmp` as the base directory
- **Memory card title overlapping trash icon:** added padding so long titles no longer clip behind the delete button
- **Memory list clipping at bottom:** added bottom padding so the last card isn't cut off by the panel edge
- **Audio endpoint 404 on macOS:** resolved `/tmp` → `/private/tmp` symlink issue and URL-encoded audio paths
- **CI build failure:** fixed black formatting issues

---

## [2026.3.10] - 2026-03-10

### Added

- **Persistent source URLs:** Source URLs from any platform (YouTube, Twitter/X, TikTok, Instagram, SoundCloud, and 1000+ sites) are now stored permanently by audio file hash in a dedicated `source_urls` table. Any future search or transcription of the same file — even after restarts, from a different path — automatically links back to the original source. No manual URL entry needed.
- **Web UI Memory Explorer:** browse, search, view, and delete stored transcriptions from the browser. Each entry shows title, duration, model size, and date. YouTube-sourced entries are marked with a YT badge.
- **Web UI memory deletion:** trash icon on each memory card with confirmation dialog. Removes the transcription, embeddings, and `.md` file.
- **Web UI YouTube timestamp linking:** after uploading a file, paste a YouTube URL inline in the results to retroactively add clickable timestamp links to all matches.
- **Web UI URL paste:** paste a YouTube or video URL directly in the search view to download and search audio without leaving the browser.
- **Web UI Share as HTML:** download any transcript as a self-contained HTML page with all styling inline.
- **Web UI Show in Finder:** reveal the original audio file in Finder (macOS), file manager (Linux), or Explorer (Windows). Uses AppleScript on macOS for reliable handling of special characters in paths.
- **Web UI favicon:** custom Augent favicon embedded as base64, ships with every install.
- **Web UI PNG banner:** Augent logo displayed in the log area, served from the package. Replaces the ASCII art banner.
- **Source URL in `.md` files:** transcription markdown files now include a `**URL:**` line in the metadata header when a source URL is available.

### Changed

- **Web UI title:** browser tab now reads "Augent Web UI" instead of "Augent"
- **Web UI tagline:** displays "Web UI v{version}" dynamically from package version
- **Web UI keywords:** changed from single-line input to resizable textarea
- **Web UI results:** row hover animation changed from border-left (caused text jitter) to clean `translateY(-1px)` on tbody rows only
- **Web UI snippets:** markdown `**` bold markers stripped from keyword matches (the UI already bolds keywords with CSS)
- **File upload naming:** uploaded files now preserve their original filename in memory instead of storing as temp file names

### Fixed

- **YouTube timestamp linking in Web UI:** `lastGrouped` was not being set in the file upload SSE path, causing the "Link timestamps" button to silently fail
- **Results header hover:** `Time | Context` header row no longer animates on hover (scoped to `tbody tr` only)
- **Show in Finder reliability:** switched from `open -R` to AppleScript on macOS for paths with special characters

---

## [2026.3.8] - 2026-03-08

### Added

- **`separate_audio` MCP tool:** audio source separation using Meta's Demucs v4. Isolates vocals from music, background noise, and other sounds. Feeds directly into the transcription pipeline for clean results on noisy recordings.
- **`separator` optional dependency group:** `pip install augent[separator]` installs Demucs. Also included in `augent[all]`.
- **Hash-based separation caching:** separated stems are stored at `~/.augent/separated/` by file hash. First run processes, every run after is instant.
- **Vocals-only mode:** default two-stem separation (vocals + no_vocals) is faster than full 4-stem. Set `vocals_only: false` for all 4 stems (vocals, drums, bass, other).
- **Installer support for Demucs:** `install.sh` now includes separator in the extras fallback chain and verifies demucs during package verification.
- **78 new tests:** CLI, TTS, speakers, and clips modules now fully tested (133 to 211 total)
- **CodeQL security scanning:** weekly + on every push/PR
- **Dependabot:** daily automated dependency and GitHub Actions updates
- **Makefile:** `make test`, `make lint`, `make fmt`, `make check` for developer convenience
- **Discord badge and link** in README

### Changed

- **Speaker diarization upgraded to pyannote-audio:** replaced the abandoned simple-diarizer (155 stars, last release 2022) with pyannote-audio (9.3k stars, actively maintained). Same tool interface, same caching, dramatically better accuracy. Requires a free Hugging Face token.

### Improved

- **CI pipeline:** added ruff + black enforcement, pip caching, Python 3.13 to test matrix
- **Ruff config:** migrated to `[tool.ruff.lint]` namespace, added per-file ignores for intentional patterns
- **Coverage reporting:** pytest-cov on Python 3.12 in CI with `[tool.coverage]` config

### Fixed

- **Insecure temp file** in `mcp.py`: replaced `tempfile.mktemp` with `NamedTemporaryFile`
- **Path validation** in `memory.py`: `realpath` + `isfile` check before file access
- **Lint violations:** 66 issues resolved across all modules (unused imports, raise-from, set comprehensions)
- **Formatting:** entire codebase now passes black

---

## [2026.2.28] - 2026-02-28

### Added

- **`context_words` parameter on `deep_search` and `search_memory`:** control how much context each result returns. Default 25 words (unchanged). Set to 150 for full evidence blocks when Claude needs to answer a question, not just find a moment
- **`dedup_seconds` parameter on `deep_search` and `search_memory`:** merge matches from the same time range to avoid redundant results. Default 0 (off). Set to 60 for Q&A workflows
- **File output on all search and transcription tools:** `transcribe_audio`, `search_audio`, `deep_search`, `search_proximity` now accept an `output` parameter for saving results directly to disk
- **XLSX export:** `.xlsx` for styled spreadsheets with bold headers and formatted timestamps, `.csv` for plain data. Auto-detected from file extension
- **Per-segment timestamps on `transcribe_audio`:** responses now include a `segments` array with `start`, `end`, `timestamp`, and `text` per segment instead of one flat text string
- **Audio trimming on `transcribe_audio`:** `start` and `duration` parameters (in seconds) to transcribe specific sections without manual ffmpeg

### Improved

- **Consistent `output` parameter:** all search and transcription tools now follow the same export pattern `search_memory` introduced in 2026.2.26

---

## [2026.2.26] - 2026-02-26

### Added

- **`search_memory` tool:** search across ALL stored transcriptions in one query, no audio_path needed
- **Keyword and semantic modes:** `search_memory` defaults to literal keyword matching; opt into meaning-based search with `mode: "semantic"`
- **CSV export:** optional `output` parameter on `search_memory` saves results as a CSV file
- **25-word snippets:** all search tools now return consistent ~25-word context snippets with keyword highlighting

### Improved

- **Keyword highlighting:** matched keywords shown in **bold** across all search results (search_audio, deep_search, search_memory, search_proximity)
- **CLI:** `augent memory search "query"` with `--semantic` and `--top-k` flags

---

## [2026.2.21] - 2026-02-21

### Changed

- **"Cache" rebranded to "Memory":** tools, CLI commands, code, and docs now use "memory" language (`list_memories`, `memory_stats`, `clear_memory`, `augent memory`)

### Improved

- **Installer UX:** animated spinners, paced output, and race condition fix for `curl|bash` piped installs
- **ASCII banner** for CLI and installer using pyfiglet

---

## [2026.2.16] - 2026-02-16

### Added

- **OpenClaw integration:** skill package for ClawHub + `augent setup openclaw` one-liner
- **Installer auto-detects OpenClaw** and configures MCP alongside Claude
- **MCP protocol tests:** 33 tests covering routing, tool listing, and error handling

---

## [2026.2.15] - 2026-02-15

### Fixed

- **TTS no longer blocks MCP:** runs in background subprocess with job polling
- Installer correctly selects framework Python for MCP config on macOS

---

## [2026.2.14] - 2026-02-14

### Improved

- **Quiz checkbox syntax:** answer options render as Obsidian checkboxes
- Answer key formatting enforced (bold number + letter, em dash, explanation)
- Claude always routes video URLs through `take_notes`, never WebFetch

---

## [2026.2.13] - 2026-02-13

### Added

- **`save_content` mode for `take_notes`:** bypasses Write tool, ensures post-processing runs
- Installer auto-installs Python 3.12 when only 3.13 is available

### Fixed

- Installer eliminates silent failures and verifies all packages
- `take_notes` embeds absolute file paths in Claude instructions
- Skip re-downloading dependencies on reinstall

---

## [2026.2.12] - 2026-02-12

### Improved

- **Lazy imports for optional dependencies:** installing mid-session works without restart
- Preserve WAV file when ffmpeg conversion fails in TTS

---

## [2026.2.9] - 2026-02-09

### Added

- **Text-to-speech:** Kokoro TTS with 54 voices across 9 languages
- **`read_aloud` option for `take_notes`:** generates spoken MP3 and embeds in Obsidian

---

## [2026.2.8] - 2026-02-08

### Added

- **`identify_speakers`:** speaker diarization, no API keys required
- **`deep_search`:** semantic search using sentence-transformers (find by meaning, not keywords)
- **`chapters`:** auto-detect topic boundaries with embedding similarity
- **5 note styles** for `take_notes`: tldr, notes, highlight, eye-candy, quiz
- **Obsidian .txt integration guide:** full setup for live-synced notes

### Changed

- Renamed `list_audio_files` → `list_files`, defaults to all common media formats
- Enforced `tiny` as default model across all tool schemas

---

## [2026.2.7] - 2026-02-07

### Added

- **`take_notes` tool:** one-click URL to formatted notes pipeline (download + transcribe + save .txt)

---

## [2026.1.31] - 2026-01-31

### Added

- **Title-based cache lookups:** search cached transcriptions by name
- **Markdown transcription files:** each cached transcription also saved as readable `.md`

---

## [2026.1.29] - 2026-01-29

### Changed

- **Python 3.10+ required** (dropped 3.9 support)

### Fixed

- Homebrew Python compatibility (PATH, PEP 668, absolute paths)
- Pinned yt-dlp to stable version for reliable downloads
- Installer handles Homebrew permission issues gracefully

---

## [2026.1.26] - 2026-01-26

### Added

- **`audio-downloader` CLI tool:** speed-optimized with aria2c (16 parallel connections)
- **`download_audio` MCP tool:** Claude can download audio directly
- Model size warnings for medium/large (resource-intensive)

### Fixed

- aria2c downloader-args format causing download failures
- Web UI default port changed from 8888 to 8282

---

## [2026.1.24] - 2026-01-24

### Added

- **Web UI v1:** local web interface with failproof startup
- **CI/CD:** GitHub Actions testing on Python 3.10, 3.11, 3.12
- **Professional installer:** one-liner `curl | bash` setup
- Logo and branding

---

## [2026.1.23] - 2026-01-23

### Added

- **Initial release**
- **MCP server** exposing tools for Claude Code and Claude Desktop
- **Transcription engine** powered by faster-whisper with word-level timestamps
- **Keyword search** with timestamped matches and context snippets
- **Proximity search:** find where keywords appear near each other
- **Batch processing:** search multiple files in parallel
- **Three-layer caching:** transcriptions, embeddings, and diarization in SQLite
- **CLI** with search, transcribe, proximity, and cache management commands
- **Export formats:** JSON, CSV, SRT, VTT, Markdown
- **Cross-platform support:** macOS, Linux, Windows
