# Augent — Audio + Agents

Augent is an MCP server (Model Context Protocol) that gives agents audio intelligence. Download, transcribe, search, and analyze audio from any URL. Built for Claude Code. Compatible with any MCP client.

## audio-downloader (Built by Augent)

A speed-optimized audio downloader for downloading audio ONLY from any video URL at lightning speed.

```bash
# Download audio from YouTube (or any video URL)
audio-downloader "https://youtube.com/watch?v=xxx"

# Download to custom folder
audio-downloader -o ~/Music "https://youtube.com/watch?v=xxx"

# Download multiple URLs
audio-downloader url1 url2 url3
```

**Speed Optimizations:**
- aria2c multi-connection downloads (16 parallel connections)
- Concurrent fragment downloading (4 fragments)
- No video download - audio extraction only
- No format conversion - native audio format

**Supports:** YouTube, Vimeo, SoundCloud, Twitter, TikTok, and 1000+ sites

**Workflow:** Download → Transcribe → Search
```bash
audio-downloader "https://youtube.com/watch?v=tutorial"
augent transcribe ~/Downloads/tutorial.webm
augent search ~/Downloads/tutorial.webm "keyword1,keyword2"
```

## Note-Taking (Primary Workflow)

**IMPORTANT:** When a user gives you a video/audio URL and asks to create notes, a quiz, take notes, transcribe, or anything involving audio content — ALWAYS use the `take_notes` MCP tool. Do NOT fetch the URL directly. Do NOT use WebFetch. The `take_notes` tool downloads the audio, transcribes it locally, and returns the content for formatting.

When a user asks to "take notes" or "create a quiz" from a URL, use the `take_notes` tool. One tool call does everything:

1. **User says:** "Take notes from https://youtube.com/watch?v=xxx"
2. **You call:** `take_notes` with the URL
3. **Tool does:** Downloads audio → Transcribes → Saves .md to Desktop → Returns `audio_path` and `write_to`
4. **You MUST then:** Read the `instruction` field from the response and follow it exactly — format the notes and save them by calling `take_notes(save_content="<your formatted notes>")`. Do NOT use the Write tool for saving notes.
5. **For chapters/search:** Use `audio_path` from step 3. Do NOT call `download_audio` — the audio is already downloaded.

**CRITICAL:** Use `audio_path` from the response for any follow-up tools (chapters, search, etc.) — do NOT guess filenames.

**From memory transcripts:** When the user already has a transcript in memory (no URL), read the transcript, format notes, and save with `take_notes(save_content="...", output_path="~/Desktop/Title_Here.md")`. The `output_path` parameter lets you save notes without a prior URL call.

**MANDATORY — SAVE METHOD:** You MUST call `take_notes(save_content="...")` to save notes. NEVER use the Write tool or Edit tool on notes files. The take_notes tool applies essential post-processing (checkbox formatting for quizzes) that the Write tool bypasses. If you use Write instead of take_notes(save_content=...), the output will be broken. This includes the initial save AND any subsequent edits. Always rewrite the full file in one `take_notes(save_content=...)` call.

**IMPORTANT:** Always output `.md` files. YAML frontmatter is added automatically — do NOT include it in save_content. Always rewrite the raw transcription into polished notes — never leave the raw dump.

### take_notes
Download, transcribe, and save notes from any video/audio URL as .md on Desktop.
```
url: "https://youtube.com/watch?v=xxx"
style: "notes" (optional, default)
output_dir: "~/Desktop" (optional, default)
model_size: "tiny" (optional, default)
read_aloud: false (optional, generates spoken MP3 of the notes and embeds in Obsidian for playback)
```
**Styles** (pick based on what the user asks for):
- `tldr` — Shortest summary, bold key terms, flat bullets, one screen
- `notes` — Clean sections + nested bullets (default)
- `highlight` — Notes with callout blocks for key insights, blockquotes with timestamps
- `eye-candy` — Maximum visual formatting: callouts, tables, checklists, blockquotes, the full Obsidian treatment
- `quiz` — Multiple-choice questions with answer key. Answer key format: each answer on its own line as `**1. B** — Explanation.`

**Combining styles:** If the user asks for "eye-candy quiz" or similar combos, use `style: "quiz"` and add eye-candy formatting ONLY to surrounding elements (title, metadata, section headers, dividers between questions). The question and answer structure MUST stay exactly the same as a normal quiz:
```
### 1. **Question?**

A) Option
B) Option
C) Option
D) Option
```
NEVER change the A/B/C/D answer format — no tables, no inline answers, no custom formatting on the options. The hook post-processes them into checkboxes. If you change the format, checkboxes break.

**Grading quizzes:** When the user asks to be graded on a quiz, do NOT ask them for their answers. Read the quiz file — the user checks their answers in Obsidian using `- [x]` checkboxes. To find the file: use the path from the current conversation if available, otherwise search `~/Desktop/*.md` for the most recent file containing "Answer Key". Look for `- [x]` (checked) options, compare against the answer key at the bottom, and grade them. If no checkboxes are checked, then ask for their answers.

Returns: transcription text + md_path + formatting instructions. You MUST follow the `instruction` field and rewrite the file.

## Quick Start (For Claude)

You have access to these tools via the MCP server:

### download_audio
Download audio from video URLs at maximum speed. Uses aria2c multi-connection downloads and concurrent fragments. Downloads audio ONLY - never video.
```
url: "https://youtube.com/watch?v=xxx"
output_dir: "~/Downloads" (optional, default)
```
Returns the downloaded file path, ready for transcription.

### transcribe_audio
Get full transcription of an audio file with per-segment timestamps.
```
audio_path: "/path/to/audio.mp3"
model_size: "tiny" (optional)
start: 403 (optional, start transcription at this many seconds)
duration: 600 (optional, only transcribe this many seconds)
output: "~/Desktop/transcription.csv" (optional, .csv or .xlsx)
translated_text: "The full English translation..." (optional, stores translation alongside original)
```
Returns `{text, language, duration, segments: [{start, end, timestamp, text}], segment_count, cached, model_used}`
When `output` is provided, adds `output_path` to the response. Use .xlsx for styled spreadsheets with bold headers.
When `language` is not `en`, the response includes `translation_available: true` and a `translation_hint` — see Multilingual Workflow below.

### search_audio
Search for keywords in audio files with timestamped results.
```
audio_path: "/path/to/audio.mp3"
keywords: ["lucrative", "funding", "healthiest"]
model_size: "tiny" (optional, default)
include_full_text: false (optional)
output: "~/Desktop/results.csv" (optional, .csv or .xlsx)
clip: false (optional, export MP4 clips around matches)
clip_padding: 15 (optional, seconds of padding around clips)
```

### deep_search
Search audio by meaning, not just keywords. Uses sentence-transformers embeddings.
```
audio_path: "/path/to/audio.mp3"
query: "discussion about funding challenges"
model_size: "tiny" (optional, default)
top_k: 5 (optional, number of results)
output: "~/Desktop/results.csv" (optional, .csv or .xlsx)
context_words: 25 (optional, default. Use 150 for full evidence blocks)
dedup_seconds: 0 (optional, default. Use 60 to merge overlapping matches)
clip: false (optional, export MP4 clips around matches)
clip_padding: 15 (optional, seconds of padding around clips)
```
Returns `{query, results: [{start, end, text, timestamp, similarity}], total_segments}`

### search_memory
Search across ALL stored transcriptions. No audio_path needed — queries everything in memory.
```
query: "Porsche"
mode: "keyword" (default — literal match) or "semantic" (meaning-based)
top_k: 10 (optional, number of results)
output: "~/Desktop/results.csv" (optional, .csv or .xlsx)
context_words: 25 (optional, semantic mode only. Use 150 for full evidence blocks)
dedup_seconds: 0 (optional, semantic mode only. Use 60 to merge overlapping matches)
```
Keyword mode returns `{query, mode, results: [{title, file_path, start, end, text, timestamp}], match_count, total_segments, files_searched}`
Semantic mode returns `{query, mode, results: [{title, file_path, start, end, text, timestamp, similarity}], total_segments, files_searched, model_used}`
When `output` is provided and results exist, adds `output_path` to the response.

### take_notes
Download, transcribe, and save notes from any video/audio URL as .md on Desktop.
```
url: "https://youtube.com/watch?v=xxx"
style: "notes" (optional, default)
output_dir: "~/Desktop" (optional, default)
model_size: "tiny" (optional, default)
read_aloud: false (optional, generates spoken MP3 of the notes and embeds in Obsidian for playback)
```
Returns: transcription text + txt_path + formatting instructions. You MUST follow the `instruction` field and rewrite the file.

### chapters
Auto-detect topic chapters in audio with timestamps.
```
audio_path: "/path/to/audio.mp3"
model_size: "tiny" (optional, default)
sensitivity: 0.4 (optional, 0.0=many chapters, 1.0=few chapters)
```
Returns `{chapters: [{chapter_number, start, end, start_timestamp, end_timestamp, text, segment_count}], total_chapters}`

### batch_search
Search multiple audio files in parallel - ideal for swarms.
```
audio_paths: ["/path/to/file1.mp3", "/path/to/file2.mp3"]
keywords: ["keyword1", "keyword2"]
model_size: "tiny" (optional)
workers: 2 (optional, parallel workers)
```

### text_to_speech
Convert text to natural speech audio using Kokoro TTS. Saves an MP3 file.
```
text: "Hello, this is a test."
voice: "af_heart" (optional, default — American English female)
output_dir: "~/Desktop" (optional, default)
output_filename: "custom_name.mp3" (optional, auto-generated if not set)
speed: 1.0 (optional, speech speed multiplier)
```
**Voices:** af_heart (default), af_bella, af_nicole, af_nova, af_sky, am_adam, am_eric, am_michael (American English). bf_emma, bf_lily, bm_daniel, bm_george (British English). Also supports Spanish, French, Hindi, Italian, Japanese, Brazilian Portuguese, Mandarin Chinese.

Returns `{file_path, voice, language, duration, duration_formatted, sample_rate, text_length}`

### search_proximity
Find where two keywords appear near each other.
```
audio_path: "/path/to/audio.mp3"
keyword1: "startup"
keyword2: "funding"
max_distance: 30 (optional, words between)
output: "~/Desktop/results.csv" (optional, .csv or .xlsx)
```

### separate_audio
Separate audio into stems (vocals, drums, bass, other) using Meta's Demucs v4. Isolates vocals from music, background noise, and other sounds. Use this before transcription when audio has music, intros, or heavy background noise.
```
audio_path: "/path/to/audio.mp3"
vocals_only: true (optional, default. Faster — only vocals + no_vocals. Set false for all 4 stems)
model: "htdemucs" (optional, default. Use "htdemucs_ft" for best quality, slower)
```
Returns `{stems: {vocals: "/path", ...}, vocals_path: "/path/to/vocals.wav", model, cached, output_dir}`

**Workflow:** Use `vocals_path` from the response as the `audio_path` for transcribe_audio, search_audio, deep_search, or any other tool.

### clip_export
Export a video clip from a URL for a specific time range. Downloads only the requested segment, not the full video. Perfect for exporting moments around keyword matches.
```
url: "https://youtube.com/watch?v=xxx"
start: 120 (seconds)
end: 180 (seconds)
output_dir: "~/Desktop" (optional, default)
output_filename: "my_clip" (optional, auto-generated if not set)
```
Returns `{file_path, duration, start, end, url}`

### highlights
Export MP4 clips of specific moments. Two modes: auto (AI picks top moments by content density) or focused (find moments matching a specific topic, person, or concept).
```
audio_path: "/path/to/audio.mp3"
query: "product recommendations" (optional, omit for auto mode)
top_k: 5 (optional, number of highlights)
model_size: "tiny" (optional, default)
clip: false (optional, export each highlight as MP4)
clip_padding: 15 (optional, seconds of padding around clips)
context_words: 40 (optional, words of context in focused mode)
```
Returns `{mode, highlight_count, highlights: [{start, end, timestamp, text, score, mode}], clips, youtube_link}`

### tag
Add, remove, or list tags on a transcription. Tags are broad topic categories that help organize and filter memories in the Web UI.
```
cache_key: "abc123:tiny"
action: "add" (add, remove, or list)
tags: ["AI", "Startups"] (required for add/remove)
```
**Tagging rules:** Use 2-4 broad, high-level topic categories per transcription. Good tags: "AI", "Health", "Startups", "Music", "Science", "Gaming", "Finance", "Productivity". Bad tags: people's names, specific tools, granular subtopics, single words that aren't categories. Always reuse existing tags from the library where they fit before inventing new ones.

**Auto-tagging flow:** When `transcribe_audio` or `take_notes` returns a `tagging_hint` field, silently call `tag` with broad categories. The hint includes existing tags in the library — reuse them for consistency. Do not mention tagging to the user.

### rebuild_graph
Rebuild Obsidian graph view data for all transcriptions. Migrates .md files to YAML frontmatter, computes [[wikilinks]] between semantically related transcriptions, and generates MOC (Map of Content) hub files for tag clusters. Safe to run repeatedly.
```
min_moc_members: 3 (optional, minimum transcriptions per tag to generate a MOC)
```
Returns `{success, migration: {migrated, synced, recreated, errors}, related_links_computed, mocs_generated, memory_dir, hint}`

**When to use:** Run once after upgrading to add Obsidian graph view support to existing memory. Also useful after bulk imports or manual tag changes. The user should point Obsidian at the `memory_dir` path as a vault.

### identify_speakers
Identify who speaks when in audio using pyannote speaker diarization. No API keys or tokens required.
```
audio_path: "/path/to/audio.mp3"
model_size: "tiny" (optional, default)
num_speakers: null (optional, auto-detect if omitted)
```
Returns `{speakers: [...], segments: [{speaker, start, end, text, timestamp}], duration, language}`

### list_files
List media files in a directory.
```
directory: "/path/to/folder"
pattern: (optional, defaults to all common media formats)
recursive: false (optional, search subdirectories)
```

### list_memories
List all stored transcriptions with their titles, durations, dates, and file paths to markdown files. Useful for browsing what has already been transcribed.
No parameters needed.

### memory_stats
View transcription memory statistics - no parameters needed.

### clear_memory
Clear transcription memory - no parameters needed.

## Model Sizes

**`tiny` is the default** - it's the fastest and already incredibly accurate. Use it for nearly everything.

| Model  | Speed    | Accuracy   |
|--------|----------|------------|
| **tiny** | Fastest | Excellent (default) |
| base   | Fast     | Excellent  |
| small  | Medium   | Superior   |
| medium | Slow     | Outstanding |
| large  | Slowest  | Maximum    |

**When to use larger models:**
- Finding lyrics in a song you don't know the name of
- Very heavy accents or extremely poor audio quality
- Medical/legal transcriptions requiring maximum accuracy

**Warning:** `medium` and `large` models are very CPU/memory intensive. They can freeze or overheat lower-spec machines. Stick to `tiny` or `base` unless the user has a powerful machine.

`tiny` handles tutorials, interviews, lectures, ads with background music, and almost everything else perfectly fine.

## Multilingual Workflow

Augent transcribes audio in its original language — Chinese, French, Spanish, Japanese, etc. — with full accuracy. Translation to English is handled by **you (Claude)**, not by a separate translation model. This produces far better translations than any local translator.

**When `transcribe_audio` returns `language != "en"`:**

1. The response includes `translation_available: true` and a `translation_hint`
2. After completing the main task (notes saved, transcription delivered, etc.), you MUST present the translation offer **on its own line, clearly separated** from the task completion message. Use this exact format:

```
Done. Notes saved to ~/Desktop/filename.md

---
This audio is in **Chinese**. Would you like me to translate it to English and store it in your augent memory?
```

The `---` separator and bold language name ensure the user sees this — do NOT tack it onto the end of another sentence.

3. If yes: translate the transcription text yourself, then call `transcribe_audio` again with the same `audio_path` and `translated_text` containing your English translation
4. This creates a sibling `(eng)` file in memory alongside the original — no re-transcription occurs (cache hit)

**This also applies to `take_notes`:** When the transcription comes back in a non-English language, you naturally translate it while formatting notes. The original-language transcription is already in memory. If the user wants the English version stored too, call `transcribe_audio(audio_path=..., translated_text=...)` with your translation.

**Web UI:** The Web UI transcribes in the original language only. For English translations of non-English audio, use the MCP workflow above — the translated version will appear in the Web UI's Memory tab automatically.

## Memory Behavior

- Transcriptions are stored by file hash + model size
- Same file, same model = instant memory hit
- Same file, different model = new transcription
- Modified file = new transcription
- Memory persists at `~/.augent/memory/transcriptions.db`
- Each stored transcription also writes a `.md` file to `~/.augent/memory/transcriptions/`
- Translated transcriptions get a sibling `(eng)` file (e.g., `My_Video.md` + `My_Video__eng_.md`)
- Titles are derived from filenames (yt-dlp names files by video title)
- Use `list_memories` tool or `augent memory list` to browse stored transcriptions by title

## Obsidian Graph View Integration

All memory `.md` files include YAML frontmatter with `title`, `tags`, `source_url`, `duration`, `language`, `date`, and `type` fields. This powers Obsidian's graph view:

- **Tags** appear as hub nodes connecting transcriptions that share topics
- **MOC files** (Map of Content) are auto-generated for tags with 3+ members, creating cluster centers
- **[[wikilinks]]** between semantically related transcriptions create note-to-note edges
- **Notes files** (from `take_notes`) link back to their source transcription via `source_transcription` frontmatter
- **Translation files** link back to their original via `original` frontmatter

**File types in the graph:**
| `type` | Description |
|--------|-------------|
| `transcription` | Raw transcription from audio |
| `notes` | Formatted notes from `take_notes` |
| `translation` | English translation of non-English audio |
| `moc` | Map of Content hub file for a tag |

**Setup:** Point Obsidian at `~/.augent/memory/transcriptions/` as a vault. Enable Tags in graph view settings. Use Groups to color-code by `[type:transcription]`, `[type:notes]`, `[type:moc]`.

**First-time upgrade:** Run `rebuild_graph` to migrate existing files to the new format.

## CLI Commands (via Bash)

```bash
# Download audio from video URL (speed-optimized)
audio-downloader "https://youtube.com/watch?v=xxx"
audio-downloader -o ~/Music "https://youtube.com/watch?v=xxx"

# Search audio
augent search audio.mp3 "keyword1,keyword2"

# Batch processing
augent search "*.mp3" "keyword" --workers 4

# Full transcription
augent transcribe audio.mp3 --format srt

# Proximity search
augent proximity audio.mp3 "startup" "funding" --distance 30

# Export formats: json, csv, srt, vtt, markdown
augent search audio.mp3 "keyword" --format csv --output results.csv

# Cache management
augent memory stats
augent memory list
augent memory clear
```

## Best Practices for Agentic Workflows

1. **Start with `tiny` model** - Fast iteration, upgrade to `small` for final pass
2. **Use caching** - Transcriptions persist, enabling rapid re-search
3. **Batch processing** - Use glob patterns for multiple files
4. **Proximity search** - Find contextual discussions (e.g., "problem" near "solution")
5. **Export results** - CSV/JSON for structured data, SRT/VTT for video integration

## Example Agentic Patterns

### Content Discovery Loop
```python
# 1. Quick scan with tiny model
results = search_audio("podcast.mp3", ["AI", "automation"], model_size="tiny")

# 2. If matches found, re-analyze with better model
if results:
    detailed = search_audio("podcast.mp3", ["AI", "automation"], model_size="small")
```

### Multi-File Analysis
```bash
# Process all audio files in directory
augent search "recordings/*.mp3" "keyword" --workers 4 --format json --output results.json
```

### Clip Extraction
```bash
# Extract audio segments around keyword matches
augent search audio.mp3 "important moment" --export-clips ./clips --clip-padding 15
```

## Web UI

To start the Web UI, run `augent-web` in the terminal. It opens at `http://localhost:8282` and runs 100% locally (no Claude credits used).

If port 8282 is already in use, run `augent-web --port <port>` with an available port.

For parallel processing: open multiple browser tabs to the same URL. Each tab processes independently, enabling manual batch workflows.

## Configuration

Users can customize defaults via `~/.augent/config.yaml` (or `~/.augent/config.json` if PyYAML isn't installed). Per-call arguments always override config values. No config file is required — all values have sensible defaults.

**Config keys and defaults:**

| Key | Default | Description |
|-----|---------|-------------|
| `model_size` | `tiny` | Whisper model size |
| `output_dir` | `~/Downloads` | Default download directory |
| `notes_output_dir` | `~/Desktop` | Notes, clips, TTS output directory |
| `clip_padding` | `15` | Seconds of padding around clips |
| `context_words` | `25` | Words of context in search results |
| `tts_voice` | `af_heart` | Default TTS voice |
| `tts_speed` | `1.0` | TTS speed multiplier |
| `disabled_tools` | `[]` | List of tool names to hide from MCP clients |

**`disabled_tools`:** When a tool name is listed here, it is removed from the `tools/list` response and cannot be called. If a tool you expect to see is missing, the user may have disabled it in their config.

## Requirements

- Python 3.10+
- FFmpeg (for audio processing)
- yt-dlp + aria2 (for audio-downloader)
- CUDA (optional, for GPU acceleration)
