"""
Augent Web UI - FastAPI + vanilla HTML/JS/CSS

Replaces the Gradio-based web UI with a clean, custom interface.
Same features: upload audio, keyword search, live streaming log, results table, JSON view.
New: export buttons (CSV, JSON, SRT).
"""

import asyncio
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from .memory import get_model_cache, get_transcription_memory
from .search import KeywordSearcher

app = FastAPI(title="Augent Web UI", docs_url=None, redoc_url=None)

# Store latest results for export
_latest_results: dict = {}
_latest_results_lock = asyncio.Lock()


def format_time(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def format_time_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Augent Web UI</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://unpkg.com/wavesurfer.js@7"></script>
<style>
*, *::before, *::after {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

:root {
    --green: #00F060;
    --green-secondary: #00A86B;
    --green-dim: rgba(0, 240, 96, 0.6);
    --green-hint: rgba(0, 240, 96, 0.4);
    --green-hover: rgba(0, 240, 96, 0.08);
    --green-border: rgba(0, 240, 96, 0.15);
    --green-border-hover: rgba(0, 240, 96, 0.35);
    --black: #000000;
    --mono: 'Monaco', 'Menlo', 'Consolas', monospace;
    --sans: 'Montserrat', sans-serif;
}

html, body {
    background: var(--black);
    color: var(--green);
    font-family: var(--sans);
    height: 100%;
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

::selection {
    background: var(--green);
    color: var(--black);
}

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, var(--green) 0%, var(--green-secondary) 100%);
    border-radius: 5px;
    border: 2px solid transparent;
}
::-webkit-scrollbar-thumb:hover { filter: brightness(1.1); }
* { scrollbar-width: thin; scrollbar-color: rgba(0, 240, 96, 0.4) transparent; }

.layout {
    display: flex;
    height: 100vh;
    padding: 24px;
    gap: 24px;
}

.sidebar {
    width: 340px;
    min-width: 340px;
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.main {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 16px;
    min-width: 0;
}

h1 {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.5px;
}

label {
    font-size: 13px;
    font-weight: 600;
    display: block;
    margin-bottom: 6px;
}

.hint {
    font-size: 11px;
    color: var(--green-dim);
    margin-top: 4px;
}

input[type="text"], select {
    width: 100%;
    background: var(--black);
    color: var(--green);
    border: 1px solid var(--green-border);
    padding: 10px 12px;
    font-family: var(--sans);
    font-size: 14px;
    border-radius: 12px;
    outline: none;
    caret-color: var(--green);
    transition: border-color 0.15s ease-out;
}

input[type="text"]::placeholder {
    color: var(--green-hint);
}

input[type="text"]:focus, select:focus {
    border-color: var(--green-border-hover);
}

select {
    cursor: pointer;
    -webkit-appearance: none;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2300F060' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 12px center;
    padding-right: 32px;
}

select option {
    background: var(--black);
    color: var(--green);
}

/* Audio upload zone */
.upload-zone {
    border: 1px dashed var(--green-border);
    border-radius: 16px;
    padding: 24px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.15s ease-out, box-shadow 0.15s ease-out;
    position: relative;
}

.upload-zone:hover, .upload-zone.dragover {
    border-color: var(--green-border-hover);
    box-shadow: 0 8px 30px rgba(0, 240, 96, 0.08);
}

.upload-zone input[type="file"] {
    position: absolute;
    inset: 0;
    opacity: 0;
    cursor: pointer;
}

.upload-zone .icon {
    font-size: 28px;
    margin-bottom: 8px;
}

.upload-zone .label {
    font-size: 13px;
    color: var(--green-dim);
}

.upload-zone.has-file {
    border-style: solid;
    border-color: var(--green-border-hover);
}

.upload-zone.has-file .label {
    color: var(--green);
    font-weight: 500;
}

/* WaveSurfer waveform */
.waveform-wrap {
    display: none;
    margin-top: 10px;
    border: 1px solid var(--green-border);
    border-radius: 12px;
    padding: 8px;
    cursor: pointer;
}

.waveform-wrap.visible {
    display: block;
}

#waveform {
    width: 100%;
    height: 48px;
}

.wave-controls {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 6px;
    padding: 0 2px;
}

.wave-time {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--green-dim);
}

.play-btn {
    background: none;
    border: 1px solid var(--green-border);
    color: var(--green);
    width: 28px;
    height: 28px;
    border-radius: 50%;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    transition: border-color 0.15s ease-out, background 0.15s ease-out;
}

.play-btn:hover {
    border-color: var(--green-border-hover);
    background: var(--green-hover);
}

/* Search button */
.search-btn {
    width: 100%;
    padding: 12px;
    background: var(--green);
    color: var(--black);
    border: none;
    font-family: var(--sans);
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
    cursor: pointer;
    border-radius: 12px;
    transition: transform 0.15s ease-out, box-shadow 0.15s ease-out;
}

.search-btn:hover {
    transform: scale(1.02);
    box-shadow: 0 8px 30px rgba(0, 240, 96, 0.2);
}

.search-btn:active {
    transform: scale(1);
}

.search-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
}

/* Tips */
.tips {
    font-size: 12px;
    color: var(--green-dim);
    line-height: 1.6;
    border-top: 1px solid var(--green-border);
    padding-top: 12px;
    margin-top: auto;
}

.tips strong {
    color: var(--green);
}

/* Tabs */
.tabs {
    display: flex;
    gap: 0;
}

.tab {
    padding: 8px 20px;
    background: var(--black);
    color: var(--green);
    border: none;
    font-family: var(--sans);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: background 0.15s ease-out;
}

.tab:hover {
    background: var(--green-hover);
}

.tab.active {
    background: var(--green);
    color: var(--black);
    border-bottom-color: var(--green);
}

/* Log area */
.log-box {
    flex: 1;
    background: var(--black);
    border: 1px solid var(--green-border);
    border-radius: 12px;
    padding: 12px;
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.5;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
    min-height: 0;
}

/* Tab panels */
.tab-panel {
    display: none;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
}

.tab-panel.active {
    display: flex;
    flex-direction: column;
    overflow-y: auto;
}

/* Results table */
.results-content {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    border: 1px solid var(--green-border);
    border-radius: 12px;
}

.results-content h3 {
    font-size: 16px;
    margin-bottom: 12px;
}

.results-content h4 {
    font-size: 14px;
    margin: 20px 0 8px;
}

.results-content table {
    width: 100%;
    border-collapse: collapse;
}

.results-content th {
    text-align: left;
    padding: 8px;
    border-bottom: 1px solid var(--green-border-hover);
    font-size: 12px;
    font-weight: 600;
}

.results-content td {
    padding: 8px;
    border-bottom: 1px solid var(--green-border);
    font-size: 13px;
}

.results-content tr {
    transition: border-color 0.15s ease-out, transform 0.15s ease-out;
}

.results-content tr:hover {
    border-left: 1px solid var(--green);
    transform: translateY(-0.5px);
}

.results-content td:first-child {
    font-family: var(--mono);
    white-space: nowrap;
    width: 70px;
}

.results-content .match-word {
    color: #FFFFFF;
    font-weight: 700;
}

/* JSON view */
.json-box {
    flex: 1;
    background: var(--black);
    border: 1px solid var(--green-border);
    border-radius: 12px;
    padding: 12px;
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.5;
    overflow-y: auto;
    white-space: pre-wrap;
    min-height: 0;
}

/* Export bar */
.export-bar {
    display: none;
    gap: 8px;
    padding: 8px 0;
    align-items: center;
}

.export-bar.visible {
    display: flex;
}

.export-bar span {
    font-size: 12px;
    font-weight: 600;
    margin-right: 4px;
}

.export-btn {
    padding: 5px 14px;
    background: var(--black);
    color: var(--green);
    border: 1px solid var(--green-border);
    font-family: var(--mono);
    font-size: 12px;
    cursor: pointer;
    border-radius: 8px;
    transition: border-color 0.15s ease-out, background 0.15s ease-out, box-shadow 0.15s ease-out;
}

.export-btn:hover {
    border-color: var(--green-border-hover);
    background: var(--green-hover);
    box-shadow: 0 4px 14px rgba(0, 240, 96, 0.1);
}
</style>
</head>
<body>

<div class="layout">
    <div class="sidebar">
        <h1>Augent</h1>

        <div>
            <label>Audio File</label>
            <div class="upload-zone" id="uploadZone">
                <input type="file" id="fileInput" accept="audio/*,video/*,.mp3,.wav,.ogg,.flac,.m4a,.webm,.mp4,.aac,.wma,.opus">
                <div class="icon">&#x2B06;</div>
                <div class="label" id="uploadLabel">Drop audio file or click to upload</div>
            </div>
            <div class="waveform-wrap" id="waveformWrap">
                <div id="waveform"></div>
                <div class="wave-controls">
                    <button class="play-btn" id="playBtn" onclick="togglePlay()">&#9654;</button>
                    <span class="wave-time" id="waveTime">0:00 / 0:00</span>
                </div>
            </div>
        </div>

        <div>
            <label>Keywords</label>
            <input type="text" id="keywords" placeholder="wormhole, hourglass, CLI">
            <div class="hint">Comma-separated</div>
        </div>

        <div>
            <label>Model</label>
            <select id="model">
                <option value="tiny" selected>tiny</option>
                <option value="base">base</option>
                <option value="small">small</option>
                <option value="medium">medium</option>
                <option value="large">large</option>
            </select>
            <div class="hint">Larger = slower but more accurate</div>
        </div>

        <button class="search-btn" id="searchBtn" onclick="startSearch()">SEARCH</button>

        <div class="tips">
            <strong>Tips:</strong><br>
            &#183; Larger models = more accurate<br>
            &#183; Results stored in memory for repeat searches
        </div>
    </div>

    <div class="main">
        <div class="log-box" id="logBox"></div>

        <div class="export-bar" id="exportBar">
            <span>Export:</span>
            <button class="export-btn" onclick="exportAs('csv')">CSV</button>
            <button class="export-btn" onclick="exportAs('json')">JSON</button>
            <button class="export-btn" onclick="exportAs('srt')">SRT</button>
            <button class="export-btn" onclick="exportAs('vtt')">VTT</button>
            <button class="export-btn" onclick="exportAs('markdown')">Markdown</button>
        </div>

        <div class="tabs">
            <button class="tab active" onclick="switchTab('results', this)">Results</button>
            <button class="tab" onclick="switchTab('json', this)">JSON</button>
        </div>

        <div class="tab-panel active" id="panel-results">
            <div class="results-content" id="resultsContent">
                <p style="color: var(--green-dim)">Upload audio and enter keywords</p>
            </div>
        </div>

        <div class="tab-panel" id="panel-json">
            <div class="json-box" id="jsonBox">{}</div>
        </div>
    </div>
</div>

<script>
let uploadedFile = null;
let wavesurfer = null;

// File upload handling
const fileInput = document.getElementById('fileInput');
const uploadZone = document.getElementById('uploadZone');
const uploadLabel = document.getElementById('uploadLabel');
const waveformWrap = document.getElementById('waveformWrap');

fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) setFile(file);
});

uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('dragover');
});

uploadZone.addEventListener('dragleave', () => {
    uploadZone.classList.remove('dragover');
});

uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) setFile(file);
});

function fmtTime(s) {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return m + ':' + String(sec).padStart(2, '0');
}

function setFile(file) {
    uploadedFile = file;
    uploadLabel.textContent = file.name;
    uploadZone.classList.add('has-file');

    // Destroy previous wavesurfer
    if (wavesurfer) {
        wavesurfer.destroy();
        wavesurfer = null;
    }

    waveformWrap.classList.add('visible');

    wavesurfer = WaveSurfer.create({
        container: '#waveform',
        height: 48,
        waveColor: '#1a1a1a',
        progressColor: '#00F060',
        cursorColor: '#00F060',
        cursorWidth: 2,
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        normalize: true,
        backend: 'WebAudio',
    });

    const url = URL.createObjectURL(file);
    wavesurfer.load(url);

    const timeEl = document.getElementById('waveTime');
    const playBtn = document.getElementById('playBtn');

    wavesurfer.on('ready', () => {
        const dur = wavesurfer.getDuration();
        timeEl.textContent = '0:00 / ' + fmtTime(dur);
    });

    wavesurfer.on('audioprocess', () => {
        const cur = wavesurfer.getCurrentTime();
        const dur = wavesurfer.getDuration();
        timeEl.textContent = fmtTime(cur) + ' / ' + fmtTime(dur);
    });

    wavesurfer.on('seeking', () => {
        const cur = wavesurfer.getCurrentTime();
        const dur = wavesurfer.getDuration();
        timeEl.textContent = fmtTime(cur) + ' / ' + fmtTime(dur);
    });

    wavesurfer.on('play', () => { playBtn.innerHTML = '&#9646;&#9646;'; });
    wavesurfer.on('pause', () => { playBtn.innerHTML = '&#9654;'; });
    wavesurfer.on('finish', () => { playBtn.innerHTML = '&#9654;'; });
}

function togglePlay() {
    if (wavesurfer) wavesurfer.playPause();
}

// Tab switching
function switchTab(name, btn) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelector('#panel-' + name).classList.add('active');
    btn.classList.add('active');
}

// Search
async function startSearch() {
    if (!uploadedFile) {
        appendLog('Upload an audio file to begin');
        return;
    }

    const keywords = document.getElementById('keywords').value.trim();
    if (!keywords) {
        appendLog('Enter keywords separated by commas');
        return;
    }

    const model = document.getElementById('model').value;
    const btn = document.getElementById('searchBtn');
    const logBox = document.getElementById('logBox');
    const resultsContent = document.getElementById('resultsContent');
    const jsonBox = document.getElementById('jsonBox');
    const exportBar = document.getElementById('exportBar');

    btn.disabled = true;
    btn.textContent = 'SEARCHING...';
    logBox.textContent = '';
    resultsContent.innerHTML = '<p>Starting...</p>';
    jsonBox.textContent = '{}';
    exportBar.classList.remove('visible');

    const formData = new FormData();
    formData.append('file', uploadedFile);
    formData.append('keywords', keywords);
    formData.append('model_size', model);

    try {
        const response = await fetch('/api/search', {
            method: 'POST',
            body: formData
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.slice(6));

                    if (data.type === 'log') {
                        appendLog(data.text);
                    } else if (data.type === 'status') {
                        resultsContent.innerHTML = '<p>' + data.text + '</p>';
                    } else if (data.type === 'results') {
                        renderResults(data.grouped, data.total);
                        jsonBox.textContent = JSON.stringify(data.grouped, null, 2);
                        exportBar.classList.add('visible');
                    }
                }
            }
        }
    } catch (err) {
        appendLog('Error: ' + err.message);
        resultsContent.innerHTML = '<p>Error: ' + err.message + '</p>';
    }

    btn.disabled = false;
    btn.textContent = 'SEARCH';
}

function appendLog(text) {
    const logBox = document.getElementById('logBox');
    logBox.textContent += text + '\\n';
    logBox.scrollTop = logBox.scrollHeight;
}

function renderResults(grouped, total) {
    const el = document.getElementById('resultsContent');
    if (total === 0) {
        el.innerHTML = '<h3>No matches found.</h3>';
        return;
    }

    let html = '<h3>Found ' + total + ' matches</h3>';

    for (const [kw, matches] of Object.entries(grouped)) {
        html += '<h4>' + escHtml(kw) + ' (' + matches.length + ')</h4>';
        html += '<table><tr><th>Time</th><th>Context</th></tr>';

        for (const m of matches) {
            const snippet = highlightKeyword(escHtml(m.snippet), kw);
            html += '<tr><td>' + escHtml(m.timestamp) + '</td><td>' + snippet + '</td></tr>';
        }

        html += '</table>';
    }

    el.innerHTML = html;
}

function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function highlightKeyword(snippet, keyword) {
    const clean = snippet.replace(/\\.\\.\\./g, '').trim();
    const re = new RegExp('(' + keyword.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + ')', 'gi');
    return clean.replace(re, '<span class="match-word">$1</span>');
}

// Export
function exportAs(format) {
    const keywords = document.getElementById('keywords').value.trim();
    window.location.href = '/api/export?format=' + format + '&keywords=' + encodeURIComponent(keywords);
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


@app.post("/api/search")
async def search_audio(
    file: UploadFile = File(...),
    keywords: str = Form(""),
    model_size: str = Form("tiny"),
):
    """Stream search results via SSE."""

    async def event_stream():
        global _latest_results

        # Save uploaded file to temp
        suffix = Path(file.filename).suffix or ".tmp"
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, dir="/tmp"
        ) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            keyword_list = [k.strip().lower() for k in keywords.split(",") if k.strip()]
            if not keyword_list:
                yield f"data: {json.dumps({'type': 'log', 'text': 'No keywords provided'})}\n\n"
                return

            filename = file.filename or "uploaded"

            def send(type_, **kwargs):
                return f"data: {json.dumps({'type': type_, **kwargs})}\n\n"

            yield send("log", text="─" * 45)
            yield send("log", text=f"  [augent] file: {filename}")
            yield send("log", text=f"  [augent] keywords: {', '.join(keyword_list)}")
            yield send("log", text=f"  [augent] model: {model_size}")
            yield send("log", text="─" * 45)
            yield send("status", text="Starting...")

            # Check memory
            memory = get_transcription_memory()
            stored = memory.get(tmp_path, model_size)

            if stored:
                yield send("log", text="  [memory] loaded from memory")
                yield send(
                    "log", text=f"  [info] duration: {format_time(stored.duration)}"
                )
                yield send("log", text="")
                yield send("status", text="Loaded from memory")
                all_words = stored.words
            else:
                yield send("log", text=f"  [model] loading {model_size}...")
                yield send("status", text="Loading model...")

                model_cache = get_model_cache()
                model = model_cache.get(model_size)

                yield send("log", text="  [model] ready")
                yield send("log", text="")
                yield send("status", text="Transcribing...")

                segments_gen, info = model.transcribe(
                    tmp_path, word_timestamps=True, vad_filter=True
                )

                duration = info.duration
                all_words = []
                segments = []

                yield send("log", text=f"  [info] duration: {format_time(duration)}")
                yield send("log", text=f"  [info] language: {info.language}")
                yield send("log", text="")

                for segment in segments_gen:
                    segments.append(
                        {
                            "start": segment.start,
                            "end": segment.end,
                            "text": segment.text,
                        }
                    )

                    ts = format_time(segment.start)
                    yield send("log", text=f"  [{ts}] {segment.text.strip()}")

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
                            for kw in keyword_list:
                                if kw in clean:
                                    yield send(
                                        "log",
                                        text=f"         >> match: '{kw}' @ {format_time(word.start)}",
                                    )

                    await asyncio.sleep(0)  # Yield control for streaming

                memory.set(
                    tmp_path,
                    model_size,
                    {
                        "text": " ".join(s["text"].strip() for s in segments),
                        "language": info.language,
                        "duration": duration,
                        "segments": segments,
                        "words": all_words,
                    },
                )

            # Search
            yield send("log", text="")
            yield send("log", text="  [search] finding matches...")
            yield send("status", text="Searching...")

            searcher = KeywordSearcher(context_words=11)
            matches = searcher.search(all_words, keyword_list)

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

            yield send("log", text="")
            yield send("log", text="─" * 45)
            yield send("log", text=f"  [done] {len(matches)} matches found")
            for kw in grouped:
                yield send("log", text=f"         {kw}: {len(grouped[kw])}")
            yield send("log", text="─" * 45)

            # Store for export
            async with _latest_results_lock:
                _latest_results = {"grouped": grouped, "total": len(matches)}

            yield send("results", grouped=grouped, total=len(matches))

        finally:
            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/export")
async def export_results(
    format: str = Query("json"),
    keywords: str = Query(""),
):
    """Export latest results in various formats."""
    async with _latest_results_lock:
        results = _latest_results.copy()

    if not results or not results.get("grouped"):
        return JSONResponse({"error": "No results to export"}, status_code=404)

    grouped = results["grouped"]
    ts = time.strftime("%Y%m%d_%H%M%S")

    if format == "json":
        content = json.dumps(grouped, indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=augent_results_{ts}.json"
            },
        )

    elif format == "csv":
        lines = ["keyword,timestamp,timestamp_seconds,snippet"]
        for kw, matches in grouped.items():
            for m in matches:
                snippet = m["snippet"].replace('"', '""').replace("**", "")
                lines.append(
                    f'"{kw}","{m["timestamp"]}",{m["timestamp_seconds"]},"{snippet}"'
                )
        content = "\n".join(lines)
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=augent_results_{ts}.csv"
            },
        )

    elif format == "srt":
        lines = []
        idx = 1
        for kw, matches in grouped.items():
            for m in matches:
                start = format_time_srt(m["timestamp_seconds"])
                end = format_time_srt(m["timestamp_seconds"] + 3)
                snippet = m["snippet"].replace("**", "").replace("...", "").strip()
                lines.append(str(idx))
                lines.append(f"{start} --> {end}")
                lines.append(f"[{kw}] {snippet}")
                lines.append("")
                idx += 1
        content = "\n".join(lines)
        return Response(
            content=content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=augent_results_{ts}.srt"
            },
        )

    elif format == "vtt":
        lines = ["WEBVTT", ""]
        for kw, matches in grouped.items():
            for m in matches:
                start = format_time_srt(m["timestamp_seconds"]).replace(",", ".")
                end = format_time_srt(m["timestamp_seconds"] + 3).replace(",", ".")
                snippet = m["snippet"].replace("**", "").replace("...", "").strip()
                lines.append(f"{start} --> {end}")
                lines.append(f"[{kw}] {snippet}")
                lines.append("")
        content = "\n".join(lines)
        return Response(
            content=content,
            media_type="text/vtt",
            headers={
                "Content-Disposition": f"attachment; filename=augent_results_{ts}.vtt"
            },
        )

    elif format == "markdown":
        lines = [f"# Augent Search Results", f"**{results['total']} matches**", ""]
        for kw, matches in grouped.items():
            lines.append(f"## {kw} ({len(matches)})")
            lines.append("")
            lines.append("| Time | Context |")
            lines.append("|------|---------|")
            for m in matches:
                snippet = m["snippet"].replace("**", "").replace("...", "").strip()
                lines.append(f"| {m['timestamp']} | {snippet} |")
            lines.append("")
        content = "\n".join(lines)
        return Response(
            content=content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f"attachment; filename=augent_results_{ts}.md"
            },
        )

    return JSONResponse({"error": f"Unknown format: {format}"}, status_code=400)


def _kill_port(port: int):
    """Kill any process using the specified port."""
    import signal
    import subprocess

    try:
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
    args = parser.parse_args()

    _kill_port(args.port)

    import time as _time

    _time.sleep(0.5)

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
