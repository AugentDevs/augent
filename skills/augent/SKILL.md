---
name: augent
description: Use when working with audio or video content, or when a user pastes a URL and asks what was said. Provides workflows for Augent MCP tools — transcription, search, notes, highlights, speaker ID, visual context, and more. Activate when the user mentions audio, video, podcasts, transcription, or URLs to media content. ALWAYS use augent tools (download_audio + transcribe_audio) for media URLs instead of WebFetch.
---

# Augent — Audio Intelligence for Agents

Augent is connected as an MCP server. All 21 tools are available. This skill teaches you how to use them effectively.

## URL Handling

When a user pastes ANY URL (tweets, YouTube, TikTok, Twitter/X, podcasts, SoundCloud, or any link with audio/video) and asks what was said, what happened, or wants the content — use `download_audio` to download, then `transcribe_audio` to get the text. Do NOT use WebFetch for media URLs.

## Key Workflows

### Note-Taking (Primary)

When a user gives you a URL and asks to create notes, take notes, transcribe, create a quiz, or anything involving audio content — use the `take_notes` tool. Do NOT fetch the URL directly.

1. Call `take_notes` with the URL
2. Read the `instruction` field from the response and follow it exactly — format the notes
3. Save by calling `take_notes(save_content="<your formatted notes>")` — do NOT use the Write tool
4. For follow-up tools (chapters, search), use the `audio_path` from step 2

**Styles:** Pick based on what the user asks for.
- `tldr` — shortest summary, one screen
- `notes` — clean sections + nested bullets (default)
- `highlight` — notes with callout blocks for key insights
- `eye-candy` — maximum visual formatting
- `quiz` — multiple-choice questions with answer key

**Quiz format:** Answer options MUST be `A)`, `B)`, `C)`, `D)` on their own lines. Never change this format — the tool post-processes them into checkboxes.

### Multilingual

When `transcribe_audio` or `take_notes` returns `language != "en"`, the response includes a `translation_hint`. After completing the main task, offer to translate:

```
Done. Notes saved to ~/Desktop/filename.md

---
This audio is in **Chinese**. Would you like me to translate it to English and store it in your augent memory?
```

If yes: translate the text yourself, then call `transcribe_audio(audio_path=..., translated_text="...")` to store the English version.

### Auto-Tagging

When `transcribe_audio` or `take_notes` returns a `tagging_hint`, silently call `tag` with 2-4 broad topic categories. Reuse existing tags from the library listed in the hint. Do not mention tagging to the user.

### Search Patterns

- **Exact words:** Use `search_audio` with keywords
- **By meaning:** Use `deep_search` with a natural language query
- **Across all files:** Use `search_memory` — no file path needed
- **Two concepts near each other:** Use `search_proximity`

### Highlights & Clips

- **Auto highlights:** `highlights` with no query — AI picks top moments
- **Focused highlights:** `highlights` with a query — finds moments matching a topic
- **Export clips:** Add `clip: true` to any highlights call, or use `clip_export` for a specific time range

### Visual Context

Use the `visual` tool to extract frames from video at moments that matter. Four modes:
- **Query mode:** `visual(url="...", query="connecting Gmail to the agent")` — finds transcript moments matching your query and extracts frames
- **Auto mode:** `visual(url="...", auto=true)` — autonomously detects visual moments (UI actions, demonstrations)
- **Manual mode:** `visual(video_path="...", timestamps=[120, 185])` — extract frames at specific timestamps
- **Assist mode:** `visual(video_path="...", assist=true)` — flags visual gaps where the user should provide their own screenshots

Frames are saved to the Obsidian vault with `![[]]` embeds. Use after `take_notes` when notes need visual context.

### Source Separation

When audio has music, intros, or background noise, call `separate_audio` first, then use the `vocals_path` from the response as the `audio_path` for transcription.

## Defaults

All defaults are configurable via `~/.augent/config.yaml`. Per-call arguments always override config.

| Setting | Default |
|---------|---------|
| Model size | `tiny` |
| Download dir | `~/Downloads` |
| Notes/clips dir | `~/Desktop` |
| Clip padding | `15s` |
| Context words | `25` |
| TTS voice | `af_heart` |

## Model Sizes

Always use `tiny` unless the user explicitly requests a different size. It handles nearly everything.

## Notes Output

Always output `.md` files. YAML frontmatter is added automatically. Always rewrite raw transcription into polished notes. Always save via `take_notes(save_content=...)`, never the Write tool.
