"""
Augent Web UI - Gradio interface with live transcription streaming
"""


# ============================================
# RUNTIME PATCH: Fix gradio_client schema bug
# Must run BEFORE importing gradio
# ============================================
def _patch_gradio_client():
    """Patch gradio_client to handle bool schemas (upstream bug)."""
    try:
        import gradio_client.utils as client_utils

        # Patch get_type to handle non-dict schemas
        original_get_type = client_utils.get_type

        def patched_get_type(schema):
            if not isinstance(schema, dict):
                return "any"
            return original_get_type(schema)

        client_utils.get_type = patched_get_type

        # Patch _json_schema_to_python_type to handle bool schemas
        original_json_schema = client_utils._json_schema_to_python_type

        def patched_json_schema(schema, defs=None):
            if schema is True or schema is False:
                return "Any"
            if schema == {}:
                return "Any"
            return original_json_schema(schema, defs)

        client_utils._json_schema_to_python_type = patched_json_schema
    except Exception:
        pass  # If patch fails, continue anyway


_patch_gradio_client()
# ============================================

import json
import os
import re
from typing import Generator, Tuple

import gradio as gr

from .memory import get_model_cache, get_transcription_memory
from .search import KeywordSearcher

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap');

/* ============================================
   GLOBAL RESET - KILL ALL BORDERS BY DEFAULT
   ============================================ */

* {
    font-family: 'Montserrat', sans-serif !important;
    color: #00F060 !important;
    background: #000 !important;
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
    accent-color: #00F060 !important;
}

:root {
    --color-accent: #00F060 !important;
    --background-fill-primary: #000 !important;
    --background-fill-secondary: #000 !important;
    --border-color-primary: transparent !important;
    --block-border-color: transparent !important;
    --block-background-fill: #000 !important;
    --input-background-fill: #000 !important;
    --button-primary-background-fill: #00F060 !important;
    --button-primary-text-color: #000 !important;
}

html, body, div, section, main, aside, header, footer,
form, fieldset, label, span, p, h1, h2, h3, h4, h5, h6,
.gradio-container, .gradio-container *, .block, .wrap, .panel,
[class*="block"], [class*="container"], [class*="wrapper"] {
    background: #000 !important;
    border: none !important;
    outline: none !important;
}

/* ============================================
   HIDE ALL SCROLLBARS GLOBALLY
   (except explicitly allowed ones)
   ============================================ */

*::-webkit-scrollbar {
    display: none !important;
    width: 0 !important;
    height: 0 !important;
    background: transparent !important;
}

* {
    scrollbar-width: none !important;
    -ms-overflow-style: none !important;
}

/* ============================================
   AUDIO WAVEFORM - GREEN & NO SCROLLBARS
   ============================================ */

/* Style audio scrollbar - black bg, green thumb */
.scroll, .scroll[part="scroll"], div.scroll, [part="scroll"] {
    scrollbar-width: thin !important;
    scrollbar-color: #00F060 #000 !important;
}
.scroll::-webkit-scrollbar,
div.scroll::-webkit-scrollbar,
[part="scroll"]::-webkit-scrollbar,
[data-testid="audio"] *::-webkit-scrollbar {
    height: 6px !important;
    background: #000 !important;
}
.scroll::-webkit-scrollbar-track,
div.scroll::-webkit-scrollbar-track,
[part="scroll"]::-webkit-scrollbar-track,
[data-testid="audio"] *::-webkit-scrollbar-track {
    background: #000 !important;
}
.scroll::-webkit-scrollbar-thumb,
div.scroll::-webkit-scrollbar-thumb,
[part="scroll"]::-webkit-scrollbar-thumb,
[data-testid="audio"] *::-webkit-scrollbar-thumb {
    background: #00F060 !important;
    border-radius: 3px !important;
}
[data-testid="audio"] * {
    scrollbar-width: thin !important;
    scrollbar-color: #00F060 #000 !important;
}

/* ============================================
   VOLUME SLIDER - GREEN
   ============================================ */

input[type="range"] {
    -webkit-appearance: none !important;
    appearance: none !important;
    background: #003318 !important;
    height: 4px !important;
    border-radius: 2px !important;
    cursor: pointer !important;
}
input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none !important;
    appearance: none !important;
    width: 14px !important;
    height: 14px !important;
    border-radius: 50% !important;
    background: #00F060 !important;
    cursor: pointer !important;
    border: none !important;
}
input[type="range"]::-moz-range-thumb {
    width: 14px !important;
    height: 14px !important;
    border-radius: 50% !important;
    background: #00F060 !important;
    cursor: pointer !important;
    border: none !important;
}
input[type="range"]::-webkit-slider-runnable-track {
    background: #003318 !important;
    height: 4px !important;
    border-radius: 2px !important;
}
input[type="range"]::-moz-range-track {
    background: #003318 !important;
    height: 4px !important;
    border-radius: 2px !important;
}

/* Audio controls - center volume slider */
[data-testid="audio"] .controls,
[data-testid="audio"] [class*="control"],
[data-testid="audio"] [class*="actions"] {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
[data-testid="audio"] input[type="range"] {
    margin: 0 8px !important;
    vertical-align: middle !important;
}

/* Make waveform completely green */
[data-testid="audio"] canvas {
    filter: sepia(100%) saturate(1000%) hue-rotate(70deg) !important;
}
wave, wave > wave, .wavesurfer-region {
    background: #00F060 !important;
}

/* Hide undo button - target by SVG path (refresh/undo icon) */
button:has(path[d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"]),
button:has(path[d*="M3.51 15"]),
button:has(path[d*="2.13-9.36"]) {
    display: none !important;
    width: 0 !important;
    height: 0 !important;
    visibility: hidden !important;
}

/* ============================================
   HIDE UNDO BUTTON IN AUDIO CONTROLS
   ============================================ */

/* Hide UNDO and TRIM buttons in audio controls */
[data-testid="audio"] button:has([data-testid="undo"]),
[data-testid="audio"] button:has([data-testid="trim"]),
[data-testid="audio"] button:has(svg[aria-label*="ndo"]),
[data-testid="audio"] button:has(svg[aria-label*="rim"]),
[data-testid="audio"] button:has(svg[aria-label*="cut"]),
[data-testid="audio"] button:has(svg[aria-label*="cissor"]),
[aria-label="undo"], [aria-label="Undo"],
[aria-label="trim"], [aria-label="Trim"],
[aria-label*="scissor"], [aria-label*="cut"],
button[aria-label*="ndo"], button[aria-label*="rim"],
/* Target the last two buttons in audio controls (undo & trim) */
[data-testid="audio"] .controls > button:nth-last-child(1),
[data-testid="audio"] .controls > button:nth-last-child(2),
[data-testid="audio"] [class*="control"] > button:nth-last-child(1),
[data-testid="audio"] [class*="control"] > button:nth-last-child(2),
[data-testid="audio"] .actions button,
[data-testid="audio"] [class*="action"] button {
    display: none !important;
    width: 0 !important;
    height: 0 !important;
    visibility: hidden !important;
    position: absolute !important;
    left: -9999px !important;
    pointer-events: none !important;
}

/* ============================================
   BUTTONS - Minimal styling
   ============================================ */

button, .btn, [role="button"] {
    background: #000 !important;
    color: #00F060 !important;
    border: none !important;
}

button svg, button path, svg {
    fill: #00F060 !important;
    stroke: #00F060 !important;
}

/* PRIMARY BUTTON - Green bg, black text */
.primary-btn, button.primary, [class*="primary"]:not([role="tabpanel"]) {
    background: #00F060 !important;
    color: #000 !important;
}
[class*="primary"]:not([role="tabpanel"]) *, [class*="primary"]:not([role="tabpanel"]) svg {
    color: #000 !important;
    fill: #000 !important;
}

/* Upload/dropzone area - no hover effects */
[data-testid="dropzone"],
[class*="upload"],
[class*="Upload"],
[class*="drop"],
[class*="Drop"],
.upload-container,
.audio-upload,
[class*="svelte"][class*="wrap"] {
    background: #000 !important;
    transition: none !important;
    border: none !important;
}
[data-testid="dropzone"]:hover,
[class*="upload"]:hover,
[class*="drop"]:hover,
[class*="upload"]:hover *,
.upload-container:hover,
[class*="svelte"]:hover {
    background: #000 !important;
    border: none !important;
    border-color: transparent !important;
    transform: none !important;
    box-shadow: none !important;
}
[data-testid="dropzone"] *,
[class*="upload"] * {
    background: transparent !important;
    color: #00F060 !important;
    fill: #00F060 !important;
}

/* ============================================
   TABS
   ============================================ */

button[role="tab"] {
    background: #000 !important;
    color: #00F060 !important;
    border: none !important;
}
button[role="tab"][aria-selected="true"] {
    background: #00F060 !important;
    color: #000 !important;
}
button[role="tab"][aria-selected="true"] * {
    color: #000 !important;
}

/* ============================================
   INPUTS - Minimal border only on inputs
   ============================================ */

input, textarea, select {
    background: #000 !important;
    color: #00F060 !important;
    border: 1px solid #003318 !important;
    caret-color: #00F060 !important;
}
input::placeholder, textarea::placeholder {
    color: #004422 !important;
}

/* ============================================
   LOG OUTPUT - Keep scrollbar for logs only
   ============================================ */

.log-output textarea,
.log-output textarea *,
textarea.scroll-hide,
[class*="log"] textarea,
[class*="textbox"] textarea {
    font-family: 'Monaco', 'Menlo', monospace !important;
    font-size: 13px !important;
    color: #00F060 !important;
    -webkit-text-fill-color: #00F060 !important;
    background: #000 !important;
    border: 1px solid #003318 !important;
    overflow-y: auto !important;
    scrollbar-width: thin !important;
    scrollbar-color: #00F060 #000 !important;
}
.log-output textarea::-webkit-scrollbar { display: block !important; width: 8px !important; }
.log-output textarea::-webkit-scrollbar-thumb { background: #00F060 !important; }
.log-output textarea::-webkit-scrollbar-track { background: #001108 !important; }

/* Hide footer */
footer { display: none !important; }

/* Selection & hover */
::selection { background: #00F060 !important; color: #000 !important; }
button:hover { background: #001a0d !important; }
[class*="primary"]:hover { background: #00D050 !important; }

/* Kill all loading/animations/overlays */
.scroll-fade, [class*="scroll-fade"], [class*="loading"], [class*="spinner"],
[class*="progress"], [class*="generating"], [class*="pending"], .loader,
.wrap.generating, .wrap.pending, [class*="eta"] {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
}

/* No animations */
*, *::before, *::after {
    animation: none !important;
    transition: none !important;
}
"""


def format_time(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def highlight_keyword_in_snippet(snippet: str, keyword: str) -> str:
    clean_snippet = snippet.replace("...", "").strip()
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    return pattern.sub(
        f"<strong style='color:#FFFFFF !important; font-weight:700 !important;'>{keyword}</strong>",
        clean_snippet,
    )


def search_audio_streaming(
    audio_path: str, keywords_str: str, model_size: str
) -> Generator[Tuple[str, str, str], None, None]:
    if not audio_path:
        yield "", "{}", "<p style='color:#00F060;'>Upload an audio file to begin</p>"
        return

    keywords = [k.strip().lower() for k in keywords_str.split(",") if k.strip()]
    if not keywords:
        yield "", "{}", "<p style='color:#00F060;'>Enter keywords separated by commas</p>"
        return

    filename = os.path.basename(audio_path)
    log_lines = []
    log_lines.append("─" * 45)
    log_lines.append(f"  [augent] file: {filename}")
    log_lines.append(f"  [augent] keywords: {', '.join(keywords)}")
    log_lines.append(f"  [augent] model: {model_size}")
    log_lines.append("─" * 45)

    yield "\n".join(log_lines), "{}", "<p style='color:#00F060;'>Starting...</p>"

    memory = get_transcription_memory()
    stored = memory.get(audio_path, model_size)

    if stored:
        log_lines.append("  [memory] loaded from memory")
        log_lines.append(f"  [info] duration: {format_time(stored.duration)}")
        log_lines.append("")
        yield "\n".join(
            log_lines
        ), "{}", "<p style='color:#00F060;'>Loaded from memory</p>"

        all_words = stored.words
        duration = stored.duration

    else:
        log_lines.append(f"  [model] loading {model_size}...")
        yield "\n".join(
            log_lines
        ), "{}", "<p style='color:#00F060;'>Loading model...</p>"

        model_cache = get_model_cache()
        model = model_cache.get(model_size)

        log_lines.append("  [model] ready")
        log_lines.append("")
        yield "\n".join(
            log_lines
        ), "{}", "<p style='color:#00F060;'>Transcribing...</p>"

        segments_gen, info = model.transcribe(
            audio_path, word_timestamps=True, vad_filter=True
        )

        duration = info.duration
        all_words = []
        segments = []

        log_lines.append(f"  [info] duration: {format_time(duration)}")
        log_lines.append(f"  [info] language: {info.language}")
        log_lines.append("")

        for segment in segments_gen:
            segments.append(
                {"start": segment.start, "end": segment.end, "text": segment.text}
            )

            ts = format_time(segment.start)
            log_lines.append(f"  [{ts}] {segment.text.strip()}")

            if segment.words:
                for word in segment.words:
                    all_words.append(
                        {
                            "word": word.word.strip(),
                            "start": word.start,
                            "end": word.end,
                        }
                    )
                    clean = word.word.lower().strip(".,!?;:'\"")
                    for kw in keywords:
                        if kw in clean:
                            log_lines.append(
                                f"         >> match: '{kw}' @ {format_time(word.start)}"
                            )

            yield "\n".join(
                log_lines
            ), "{}", "<p style='color:#00F060;'>Transcribing...</p>"

        memory.set(
            audio_path,
            model_size,
            {
                "text": " ".join(s["text"].strip() for s in segments),
                "language": info.language,
                "duration": duration,
                "segments": segments,
                "words": all_words,
            },
        )

    log_lines.append("")
    log_lines.append("  [search] finding matches...")
    yield "\n".join(log_lines), "{}", "<p style='color:#00F060;'>Searching...</p>"

    searcher = KeywordSearcher(context_words=11)
    matches = searcher.search(all_words, keywords)

    grouped = {}
    for m in matches:
        kw = m.keyword
        if kw not in grouped:
            grouped[kw] = []
        grouped[kw].append(
            {
                "timestamp": m.timestamp,
                "timestamp_seconds": m.timestamp_seconds,
                "snippet": m.snippet,
            }
        )

    log_lines.append("")
    log_lines.append("─" * 45)
    log_lines.append(f"  [done] {len(matches)} matches found")
    for kw in grouped:
        log_lines.append(f"         {kw}: {len(grouped[kw])}")
    log_lines.append("─" * 45)

    results_json = json.dumps(grouped, indent=2)

    html_parts = []
    html_parts.append("<div style='font-family:Montserrat,sans-serif;color:#00F060;'>")
    html_parts.append(
        f"<h3 style='color:#00F060;margin-bottom:16px;'>Found {len(matches)} matches</h3>"
    )

    if len(matches) == 0:
        html_parts.append("<p>No matches found.</p>")
    else:
        for kw, kw_matches in grouped.items():
            html_parts.append(
                f"<h4 style='color:#00FF00;margin:16px 0 8px;'>{kw} ({len(kw_matches)})</h4>"
            )
            html_parts.append("<table style='width:100%;border-collapse:collapse;'>")
            html_parts.append(
                "<tr><th style='text-align:left;padding:8px;border-bottom:1px solid #00F060;width:80px;color:#00F060;'>Time</th>"
            )
            html_parts.append(
                "<th style='text-align:left;padding:8px;border-bottom:1px solid #00F060;color:#00F060;'>Context</th></tr>"
            )

            for m in kw_matches:
                ts = m["timestamp"]
                snippet_html = highlight_keyword_in_snippet(m["snippet"], kw)

                html_parts.append(f"""<tr>
                    <td style='padding:8px;border-bottom:1px solid #002010;color:#00F060;font-family:Monaco,monospace;'>{ts}</td>
                    <td style='padding:8px;border-bottom:1px solid #002010;color:#00F060;'>{snippet_html}</td>
                </tr>""")

            html_parts.append("</table>")

    html_parts.append("</div>")

    yield "\n".join(log_lines), results_json, "\n".join(html_parts)


def create_demo() -> gr.Blocks:
    with gr.Blocks(
        title="Augent Web UI", analytics_enabled=False, css=CUSTOM_CSS
    ) as demo:
        gr.Markdown("# Augent")

        with gr.Row():
            with gr.Column(scale=1):
                audio_input = gr.Audio(
                    type="filepath", label="Audio File", sources=["upload"]
                )

                keywords_input = gr.Textbox(
                    label="Keywords",
                    placeholder="wormhole, hourglass, CLI",
                    info="Comma-separated",
                )

                model_dropdown = gr.Dropdown(
                    choices=["tiny", "base", "small", "medium", "large"],
                    value="tiny",
                    label="Model",
                    info="Larger = slower but more accurate",
                )

                search_btn = gr.Button(
                    "SEARCH", variant="primary", size="lg", elem_classes=["primary-btn"]
                )

                gr.Markdown("""
---
**Tips:**
- Larger models = more accurate
- Results stored in memory for repeat searches
                """)

            with gr.Column(scale=2):
                log_output = gr.Textbox(
                    label="Live Log",
                    lines=25,
                    max_lines=25,
                    autoscroll=True,
                    elem_classes=["log-output"],
                )

                # ALWAYS force scroll to bottom + Shadow DOM fixes
                gr.HTML("""<script>
// Auto-scroll log
setInterval(function() {
    var ta = document.querySelector('.log-output textarea');
    if (ta) ta.scrollTop = ta.scrollHeight;
}, 50);

// Shadow DOM style injection - scrollbars, volume sliders, everything
var shadowCSS = `
    /* Scrollbar styling */
    .scroll, [part="scroll"], div.scroll, * {
        scrollbar-width: thin !important;
        scrollbar-color: #00F060 #000 !important;
    }
    ::-webkit-scrollbar {
        height: 8px !important;
        width: 8px !important;
        background: #000 !important;
    }
    ::-webkit-scrollbar-track {
        background: #000 !important;
    }
    ::-webkit-scrollbar-thumb {
        background: #00F060 !important;
        border-radius: 4px !important;
    }

    /* Volume slider styling */
    input[type="range"] {
        -webkit-appearance: none !important;
        appearance: none !important;
        background: #003318 !important;
        height: 4px !important;
        border-radius: 2px !important;
    }
    input[type="range"]::-webkit-slider-thumb {
        -webkit-appearance: none !important;
        width: 14px !important;
        height: 14px !important;
        border-radius: 50% !important;
        background: #00F060 !important;
        border: none !important;
    }
    input[type="range"]::-moz-range-thumb {
        width: 14px !important;
        height: 14px !important;
        border-radius: 50% !important;
        background: #00F060 !important;
        border: none !important;
    }
    input[type="range"]::-webkit-slider-runnable-track {
        background: #003318 !important;
    }

    /* Center volume slider */
    .controls, [class*="control"] {
        display: flex !important;
        align-items: center !important;
    }
    input[type="range"] {
        margin: 0 8px !important;
        vertical-align: middle !important;
    }
`;

function injectIntoShadow(shadowRoot) {
    if (shadowRoot._augentInjected) return;
    shadowRoot._augentInjected = true;

    // Inject styles
    var style = document.createElement('style');
    style.textContent = shadowCSS;
    shadowRoot.appendChild(style);

    // Force style scroll elements directly
    var scrollEls = shadowRoot.querySelectorAll('.scroll, [part="scroll"]');
    scrollEls.forEach(function(el) {
        el.style.scrollbarWidth = 'thin';
        el.style.scrollbarColor = '#00F060 #000';
        el.style.setProperty('--scrollbar-color', '#00F060');
        el.style.setProperty('--scrollbar-track', '#000');
    });

    // Force style range inputs directly
    var rangeEls = shadowRoot.querySelectorAll('input[type="range"]');
    rangeEls.forEach(function(el) {
        el.style.background = '#003318';
        el.style.accentColor = '#00F060';
        el.style.margin = '0 8px';
        el.style.verticalAlign = 'middle';
    });

    // Center controls containers
    var controlEls = shadowRoot.querySelectorAll('.controls, [class*="control"]');
    controlEls.forEach(function(el) {
        el.style.display = 'flex';
        el.style.alignItems = 'center';
        el.style.justifyContent = 'center';
    });
}

// Hide undo button by finding SVG with specific path
function hideUndoButton() {
    // Find all buttons with SVGs
    document.querySelectorAll('button svg, button path').forEach(function(el) {
        var path = el.getAttribute('d') || '';
        var parentPath = el.closest('path');
        if (parentPath) path = parentPath.getAttribute('d') || path;

        // Check for undo icon path patterns
        if (path.includes('M3.51') || path.includes('2.13-9.36') || path.includes('L1 10')) {
            var btn = el.closest('button');
            if (btn) {
                btn.style.display = 'none';
                btn.style.visibility = 'hidden';
                btn.style.width = '0';
                btn.style.height = '0';
                btn.style.position = 'absolute';
                btn.style.left = '-9999px';
            }
        }
    });
}

// Recursive shadow DOM traversal
function findAllShadowRoots(root) {
    root.querySelectorAll('*').forEach(function(el) {
        if (el.shadowRoot) {
            injectIntoShadow(el.shadowRoot);
            findAllShadowRoots(el.shadowRoot);
        }
    });
}

// Run periodically
setInterval(function() {
    findAllShadowRoots(document);
    hideUndoButton();
}, 300);

// Initial run
setTimeout(function() {
    findAllShadowRoots(document);
    hideUndoButton();
}, 100);
</script>""")

                with gr.Tabs():
                    with gr.TabItem("Results"):
                        results_html = gr.HTML(
                            value="<p style='color:#00F060;'>Upload audio and enter keywords</p>"
                        )
                    with gr.TabItem("JSON"):
                        results_json = gr.Code(language="json", lines=15)

        search_btn.click(
            fn=search_audio_streaming,
            inputs=[audio_input, keywords_input, model_dropdown],
            outputs=[log_output, results_json, results_html],
            show_progress="hidden",
        )

        gr.Markdown("---\n**Augent**")

    return demo


demo = create_demo()


def _kill_port(port: int):
    """Kill any process using the specified port."""
    import signal
    import subprocess

    try:
        # Find process using the port
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True
        )
        pids = result.stdout.strip().split("\n")
        for pid in pids:
            if pid:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except (ProcessLookupError, ValueError):
                    pass
    except Exception:
        pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Augent Web UI")
    parser.add_argument(
        "--port", "-p", type=int, default=9797, help="Port to run on (default: 9797)"
    )
    parser.add_argument(
        "--share", action="store_true", help="Create public Gradio link"
    )
    args = parser.parse_args()

    # Auto-kill anything on the port first
    _kill_port(args.port)

    import time

    time.sleep(0.5)  # Brief pause to ensure port is freed

    demo.launch(
        server_name="127.0.0.1",
        server_port=args.port,
        share=args.share,
        show_error=True,
    )


if __name__ == "__main__":
    main()
