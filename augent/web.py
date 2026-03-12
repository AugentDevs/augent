"""
Augent Web UI - FastAPI + vanilla HTML/JS/CSS

Two views:
  Search  — Upload audio or paste a URL, keyword search, streaming log, results, exports
  Memory  — Browse all stored transcriptions, full transcript view, cross-memory search,
            shareable HTML export, Show in Finder
"""

import asyncio
import html as html_mod
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
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


# --- YouTube helpers (copied from mcp.py to keep web.py self-contained) ---

_YOUTUBE_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)"
    r"([a-zA-Z0-9_-]{11})"
)


def _extract_youtube_id(url: str) -> str:
    if not url:
        return ""
    m = _YOUTUBE_VIDEO_ID_RE.search(url)
    return m.group(1) if m else ""


def _youtube_timestamp_link(source_url: str, seconds: float) -> str:
    video_id = _extract_youtube_id(source_url)
    if not video_id:
        return ""
    return f"https://youtube.com/watch?v={video_id}&t={int(seconds)}"


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Augent Web UI</title>
<link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAAXNSR0IArs4c6QAAAMZlWElmTU0AKgAAAAgABgESAAMAAAABAAEAAAEaAAUAAAABAAAAVgEbAAUAAAABAAAAXgEoAAMAAAABAAIAAAExAAIAAAAVAAAAZodpAAQAAAABAAAAfAAAAAAAAABIAAAAAQAAAEgAAAABUGl4ZWxtYXRvciBQcm8gMy43LjEAAAAEkAQAAgAAABQAAACyoAEAAwAAAAEAAQAAoAIABAAAAAEAAAAgoAMABAAAAAEAAAAgAAAAADIwMjY6MDM6MTAgMDg6NTI6NDIAVmGTLAAAAAlwSFlzAAALEwAACxMBAJqcGAAAA7BpVFh0WE1MOmNvbS5hZG9iZS54bXAAAAAAADx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iIHg6eG1wdGs9IlhNUCBDb3JlIDYuMC4wIj4KICAgPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4KICAgICAgPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIKICAgICAgICAgICAgeG1sbnM6ZXhpZj0iaHR0cDovL25zLmFkb2JlLmNvbS9leGlmLzEuMC8iCiAgICAgICAgICAgIHhtbG5zOnhtcD0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wLyIKICAgICAgICAgICAgeG1sbnM6dGlmZj0iaHR0cDovL25zLmFkb2JlLmNvbS90aWZmLzEuMC8iPgogICAgICAgICA8ZXhpZjpQaXhlbFlEaW1lbnNpb24+MzI8L2V4aWY6UGl4ZWxZRGltZW5zaW9uPgogICAgICAgICA8ZXhpZjpQaXhlbFhEaW1lbnNpb24+MzI8L2V4aWY6UGl4ZWxYRGltZW5zaW9uPgogICAgICAgICA8eG1wOkNyZWF0b3JUb29sPlBpeGVsbWF0b3IgUHJvIDMuNy4xPC94bXA6Q3JlYXRvclRvb2w+CiAgICAgICAgIDx4bXA6Q3JlYXRlRGF0ZT4yMDI2LTAzLTEwVDA4OjUyOjQyKzAxOjAwPC94bXA6Q3JlYXRlRGF0ZT4KICAgICAgICAgPHhtcDpNZXRhZGF0YURhdGU+MjAyNi0wMy0xMFQwODo1MzozMCswMTowMDwveG1wOk1ldGFkYXRhRGF0ZT4KICAgICAgICAgPHRpZmY6WFJlc29sdXRpb24+NzIwMDAwLzEwMDAwPC90aWZmOlhSZXNvbHV0aW9uPgogICAgICAgICA8dGlmZjpSZXNvbHV0aW9uVW5pdD4yPC90aWZmOlJlc29sdXRpb25Vbml0PgogICAgICAgICA8dGlmZjpZUmVzb2x1dGlvbj43MjAwMDAvMTAwMDA8L3RpZmY6WVJlc29sdXRpb24+CiAgICAgICAgIDx0aWZmOk9yaWVudGF0aW9uPjE8L3RpZmY6T3JpZW50YXRpb24+CiAgICAgIDwvcmRmOkRlc2NyaXB0aW9uPgogICA8L3JkZjpSREY+CjwveDp4bXBtZXRhPgplFKxaAAAFNklEQVRYCZXXX6zXdR3HcU4hFmqIIUYqoDuGWcLcnDVWcINtbW7Oqy5zzZvSG7utNp1zttbWRd20tnTTuVYX6a3h3CCcWs7WEBQLgY6AgiIVVqIcn4+z3/d0EA7nx3t77vP9fX7fz+f9ev/5fH7nTCz6mE1PTy9takV8JjxfGWtH4+WNn45PxkR8avT8YeN/g30Q/4w3Yyr2j57/03gsjk5MTJxsnDGbzFiOL+7hm/Gl4PjaWB6H4mCwT8SFQYRxcdhjOmz6v3hv9GzOO6tjWbwRB8I7W+P5hHwwV8AvmtwUR+IL8VxQ7flfsTveDxsTwrlMMHOyMETm+8tCMNb+Lewjmy/EV+PbCdjhxcE293BpSL1RKjfES8GR71fFBcHhELGRMO97b0lcHzeH9O+JO4IQmZC9q2IyZtJnXFQJLLgnKNUDb8WJuCL+ElJ5SciKzTgUwFCCHmdSzon5d4IYmTkVK0OfELw9flYGjswtgUWc3xlbghNNJyp18/lw6BVCzA82iPDe8eDk6tCkEIh5ZXssfp9zAf4/Az6wUTN+vcefhEXvho2pF81FoUxSqRyci1AZNODwPmdDw8ri/vhR7NF8jTM2m4FhYhgTckPP94V+EIGySKONOTJHGFHmREqcUZkOjsaljfrop0PUPc/avAK8kYh1DT+IjSGyw/F2cCxqzYihmY1EDGJ990SotxKeYecU4O1E6NgH48o4EiLWAxwNJeBoaE7ZkQXZ+k08nHPlOastKMCqRHD421DLVcHJsdEoE0rgnc+Gz4fiD/FQzpVqXhtLgNWJuK3hgfh7KAdH1hulXhacDAJl5+6c72w8p1E+rr3Qi8/EdaE3dPhcI0C0fgd2xK5Y0IbmWfDFXlD/A3FNqKku/0fsi6nwPVFfiaeKXmYWtLEz0IZVYXpPOz4bwy3IoT3+HU4GIeYcu7FsbAGj3VxMk+FkOAGcErNk9JmQk4k1N5adrwBN5rhtC8+uZaOrl3PHb32MbecrYHk7O263hGaTEfeCtLsxnYoTjm1ZOOvF0/en2dgC2tTmN4ZudydoYHMwp+lk4BtB4NOxoI0toJ0+N8IJuCGWhtoToub6QXn+GlsSvL0szHsD9s6MjSVgFP3XWrEx3IDSPxWcil4f+HVUHmwOvfDnOKdJ34KWAD+/T8bBcNlcG1eHugvCT7V7YF8Q9vnR+MOyQOy8tqCAnK9s9c9DZKvi8tgfxGhC6Vd7vwOrwzsvh57QK48kQqbOavMKGKV9Xau+G5tClByLaFm474dfQ8448R1Ra0J28Mt4PBHvNJ5h5xKg3veGzTjm5PrQeJy8F5pMBpRBFmRpecjOvnA8if91/CoRextPszMEFLmNvh+3h+Zyrd4auv2P8VZoPGaEfXw/zMvczfFKPB9+SY/G/YnY2jhrswJyTP2WELV0rY7DsTaIcLG4+aApHcOPl8BtqAwaFZOxJl4NPSI7gng0/GNycq4Af3ptDhnghMNjYVNipN6tJ+2cOPOeRS166dYX1socrJ8K64l1l+wOf119LwEvzRWwq0ncGH8K9/uGWByvxbuh7uatGy4iz6eCoKHbifH9qrguDsTeWBlfDCJ2JODHcwXc1eR34sVYH5OxLQ4FEaJz9m0qldZqQBkYIibg7XgjrPOZuC8HITtCeQUmAzvnCrDJTfGtUGPRXhHOvePke5vb4HiImAB7EKFERC6LFaEU3lEGjWuNeXfE73IuIzOLjbNWM6onx2tCtJy7ZmFzn6UShHqfEMJETSRnesjdQcTRmIrXc6x/Zu0jpHyg2acKr1sAAAAASUVORK5CYII=">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://unpkg.com/wavesurfer.js@7"></script>
<style>
*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }

:root {
    --green: #00F060;
    --green-secondary: #00A86B;
    --green-dim: rgba(0, 240, 96, 0.6);
    --green-hint: rgba(0, 240, 96, 0.4);
    --green-hover: rgba(0, 240, 96, 0.08);
    --green-border: rgba(0, 240, 96, 0.15);
    --green-border-hover: rgba(0, 240, 96, 0.35);
    --black: #000000;
    --mono: 'Monaco','Menlo','Consolas', monospace;
    --sans: 'Montserrat', sans-serif;
}

html, body {
    background: var(--black);
    color: var(--green);
    font-family: var(--sans);
    height: 100%;
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
}

::selection { background: var(--green); color: var(--black); }

::-webkit-scrollbar { width:10px; height:10px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, var(--green) 0%, var(--green-secondary) 100%);
    border-radius:5px; border:2px solid transparent;
}
* { scrollbar-width:thin; scrollbar-color:rgba(0,240,96,0.4) transparent; }

/* ---- Top nav ---- */
.top-nav {
    display: flex;
    align-items: center;
    padding: 0 24px;
    border-bottom: 1px solid var(--green-border);
    height: 48px;
    gap: 0;
}
.top-nav .brand {
    font-size: 18px;
    font-weight: 700;
    margin-right: 32px;
    letter-spacing: -0.5px;
}
.nav-btn {
    padding: 0 20px;
    height: 48px;
    background: none;
    border: none;
    color: var(--green-dim);
    font-family: var(--sans);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: color 0.15s;
}
.nav-btn:hover { color: var(--green); }
.nav-btn.active { color: var(--green); border-bottom-color: var(--green); }

/* ---- Views ---- */
.view { display: none; height: calc(100vh - 48px); }
.view.active { display: flex; }

/* ======== SEARCH VIEW ======== */
.search-view {
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

label { font-size:13px; font-weight:600; display:block; margin-bottom:6px; }
.hint { font-size:11px; color:var(--green); margin-top:4px; }

input[type="text"], textarea, select {
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
textarea {
    min-height: 44px;
    height: 44px;
    resize: vertical;
    line-height: 1.5;
    word-wrap: break-word;
    overflow-wrap: break-word;
}
input[type="text"]::placeholder, textarea::placeholder { color: var(--green-hint); }
input[type="text"]:focus, textarea:focus, select:focus { border-color: var(--green-border-hover); }

select {
    cursor: pointer;
    -webkit-appearance: none;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2300F060' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 12px center;
    padding-right: 32px;
}
select option { background:var(--black); color:var(--green); }

/* Upload zone */
.upload-zone {
    border: 1px dashed var(--green-border);
    border-radius: 16px;
    padding: 24px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.15s, box-shadow 0.15s;
    position: relative;
}
.upload-zone:hover, .upload-zone.dragover {
    border-color: var(--green-border-hover);
    box-shadow: 0 8px 30px rgba(0,240,96,0.08);
}
.upload-zone input[type="file"] { position:absolute; inset:0; opacity:0; cursor:pointer; }
.upload-zone .icon { font-size:28px; margin-bottom:8px; }
.upload-zone .label { font-size:13px; color:var(--green); }
.upload-zone.has-file { border-style:solid; border-color:var(--green-border-hover); }
.upload-zone.has-file .label { color:var(--green); font-weight:500; }
.clear-btn {
    position:absolute; top:6px; right:6px; z-index:2;
    width:22px; height:22px; border-radius:50%;
    background:rgba(0,240,96,0.12); border:1px solid var(--green-border);
    color:var(--green); font-size:0;
    display:none; padding:0; cursor:pointer;
}
.clear-btn::before, .clear-btn::after {
    content:''; position:absolute; top:50%; left:50%;
    width:10px; height:1.5px; background:var(--green);
    border-radius:1px;
}
.clear-btn::before { transform:translate(-50%,-50%) rotate(45deg); }
.clear-btn::after { transform:translate(-50%,-50%) rotate(-45deg); }
.clear-btn:hover { background:rgba(0,240,96,0.25); }
.upload-zone.has-file .clear-btn { display:flex; }
.url-wrap { position:relative; }
.url-wrap input { padding-right:32px; }
.url-wrap .clear-btn { top:50%; right:8px; transform:translateY(-50%); display:none; }
.url-wrap.has-url .clear-btn { display:flex; }

/* URL input section */
.url-section {
    margin-top: 12px;
}

/* WaveSurfer */
.waveform-wrap { display:none; margin-top:10px; border:1px solid var(--green-border); border-radius:12px; padding:10px 12px; }
.waveform-wrap.visible { display:block; }
#waveform { width:100%; height:48px; cursor:pointer; }
.wave-controls { display:flex; align-items:center; gap:8px; margin-top:8px; }
.wave-btn {
    background:none; border:1px solid var(--green-border); color:var(--green);
    width:28px; height:28px; border-radius:50%; cursor:pointer;
    display:flex; align-items:center; justify-content:center; font-size:11px;
    transition: border-color 0.15s, background 0.15s; flex-shrink:0;
}
.wave-btn:hover { border-color:var(--green-border-hover); background:var(--green-hover); }
.wave-btn svg { width:12px; height:12px; }
.wave-time { font-family:var(--mono); font-size:11px; color:var(--green); }
.wave-volume { display:flex; align-items:center; gap:6px; margin-left:auto; }
.wave-volume input[type="range"] {
    -webkit-appearance:none; appearance:none; width:70px; height:3px;
    background:var(--green-border); border-radius:2px; outline:none; cursor:pointer;
}
.wave-volume input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance:none; width:10px; height:10px; border-radius:50%;
    background:var(--green); cursor:pointer;
}
.wave-volume svg { width:14px; height:14px; color:var(--green); flex-shrink:0; }

/* Search button */
.search-btn {
    width:100%; padding:12px; background:var(--green); color:var(--black);
    border:none; font-family:var(--sans); font-size:15px; font-weight:700;
    letter-spacing:1px; cursor:pointer; border-radius:12px;
    transition: transform 0.15s, box-shadow 0.15s;
}
.search-btn:hover { transform:scale(1.02); box-shadow:0 8px 30px rgba(0,240,96,0.2); }
.search-btn:active { transform:scale(1); }
.search-btn:disabled { opacity:0.4; cursor:not-allowed; transform:none; box-shadow:none; }

.tips {
    font-size:11px; color:var(--green); line-height:1.7;
    border-top:1px solid var(--green-border); padding-top:12px; margin-top:auto;
}
.tips strong { color:var(--green); font-size:11px; }
.tips .tip-line { display:block; padding-left:10px; text-indent:-10px; }

/* Tabs */
.tabs { display:flex; gap:0; }
.tab {
    padding:8px 20px; background:var(--black); color:var(--green); border:none;
    font-family:var(--sans); font-size:13px; font-weight:600; cursor:pointer;
    border-bottom:2px solid transparent; transition:background 0.15s;
}
.tab:hover { background:var(--green-hover); }
.tab.active { background:var(--green); color:var(--black); border-bottom-color:var(--green); }

/* Log */
.log-box {
    flex:1; background:var(--black); border:1px solid var(--green-border);
    border-radius:12px; font-family:var(--mono); font-size:13px;
    line-height:1.5; overflow-y:auto; min-height:0; color:var(--green);
    display:flex; flex-direction:column;
}
.log-banner {
    flex-shrink:0; padding:20px 16px 12px 16px;
    pointer-events:none; user-select:none; -webkit-user-select:none;
}
.log-banner-img {
    display:block; width:320px; height:auto;
    image-rendering: -webkit-optimize-contrast;
    pointer-events:none; -webkit-user-drag:none;
}
.log-tagline {
    font-family: var(--sans); font-size:11px; font-weight:600;
    letter-spacing:1px; color:var(--green-dim); margin-top:8px;
}
.log-text {
    flex:1; padding:0 16px 12px; white-space:pre-wrap; word-break:break-word;
}

.tab-panel { display:none; flex:1; min-height:0; overflow:hidden; }
.tab-panel.active { display:flex; flex-direction:column; overflow:hidden; }

/* Results table */
.results-content {
    flex:1; overflow-y:auto; padding:12px;
    border:1px solid var(--green-border); border-radius:12px;
}
.results-content h3 { font-size:16px; margin-bottom:12px; }
.results-content h4 { font-size:14px; margin:20px 0 8px; }
.results-content table { width:100%; border-collapse:collapse; }
.results-content th { text-align:left; padding:8px; border-bottom:1px solid var(--green-border-hover); font-size:12px; font-weight:600; }
.results-content td { padding:8px; border-bottom:1px solid var(--green-border); font-size:13px; }
.results-content tbody tr { transition: transform 0.12s ease-out; }
.results-content tbody tr:hover { transform:translateY(-1px); }
.results-content td:first-child { font-family:var(--mono); white-space:nowrap; width:70px; }
.results-content .match-word { color:#FFFFFF; font-weight:700; }

/* Progress bar */
.progress-bar-wrap {
    padding: 12px;
    flex-shrink: 0;
}
.progress-bar-wrap.hidden { display: none; }
.progress-bar-track {
    height: 4px;
    background: var(--green-border);
    border-radius: 2px;
    overflow: hidden;
}
.progress-bar-fill {
    height: 100%;
    width: 0%;
    background: var(--green);
    border-radius: 2px;
    transition: width 0.3s ease-out;
}
.progress-bar-label {
    font-size: 13px;
    color: var(--green);
    margin-top: 6px;
    font-family: var(--mono);
}

/* Spinner */
.spinner-wrap {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    flex-shrink: 0;
}
.spinner-wrap.hidden { display: none; }
.spinner-label {
    font-size: 13px;
    color: var(--green);
    font-family: var(--mono);
}
.wormhole-spinner {
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    animation: wormhole-spin 1.8s linear infinite;
}
.wormhole-spinner circle {
    fill: none;
    stroke: var(--green);
    stroke-linecap: round;
}
@keyframes wormhole-spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
.results-content a { color:var(--green); text-decoration:none; }
.results-content a:hover { text-decoration:underline; }
.yt-hint {
    font-size:12px; color:var(--green-dim); margin-bottom:12px; padding:10px 12px;
    border:1px solid var(--green-border); border-radius:8px;
    display:flex; align-items:center; gap:8px; flex-wrap:wrap;
}
.yt-hint input {
    flex:1; min-width:200px; background:var(--black); color:var(--green);
    border:1px solid var(--green-border); border-radius:6px; padding:6px 10px;
    font-family:var(--sans); font-size:12px; outline:none;
}
.yt-hint input::placeholder { color:var(--green-hint); }
.yt-hint input:focus { border-color:var(--green-border-hover); }
.yt-hint button {
    background:none; border:1px solid var(--green-border); color:var(--green);
    padding:6px 12px; border-radius:6px; cursor:pointer; font-size:12px;
    font-family:var(--sans); font-weight:600; transition:background 0.15s;
}
.yt-hint button:hover { background:var(--green-hover); }

.json-box {
    flex:1; background:var(--black); border:1px solid var(--green-border);
    border-radius:12px; padding:12px; font-family:var(--mono); font-size:13px;
    line-height:1.5; overflow-y:auto; white-space:pre-wrap; min-height:0;
}

/* Export bar */
.export-bar { display:none; gap:8px; padding:8px 0; align-items:center; }
.export-bar.visible { display:flex; }
.export-bar span { font-size:12px; font-weight:600; margin-right:4px; }
.export-btn {
    padding:5px 14px; background:var(--black); color:var(--green);
    border:1px solid var(--green-border); font-family:var(--mono); font-size:12px;
    cursor:pointer; border-radius:8px;
    transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
}
.export-btn:hover { border-color:var(--green-border-hover); background:var(--green-hover); box-shadow:0 4px 14px rgba(0,240,96,0.1); }

/* Clip export */
.clip-btn {
    background:none; border:none; cursor:pointer; padding:2px 4px;
    color:var(--green-dim); opacity:0.5; transition:opacity 0.15s;
    vertical-align:middle; margin-left:6px;
}
.clip-btn:hover { opacity:1; }
.clip-btn svg { width:14px; height:14px; vertical-align:middle; }
.clip-modal {
    position:fixed; inset:0; z-index:1000;
    display:flex; align-items:center; justify-content:center;
    background:rgba(0,0,0,0.7); backdrop-filter:blur(4px);
}
.clip-modal-box {
    background:var(--black); border:1px solid var(--green-border-hover);
    border-radius:16px; padding:24px 28px; min-width:360px; max-width:440px;
    box-shadow:0 20px 60px rgba(0,240,96,0.1);
}
.clip-modal-box h3 { margin:0 0 16px; font-size:15px; }
.clip-modal-box label { display:block; font-size:12px; font-weight:600; margin:10px 0 4px; }
.clip-modal-box input[type="text"] {
    width:100%; box-sizing:border-box;
    background:var(--input-bg); border:1px solid var(--green-border);
    color:var(--green); padding:8px 10px; border-radius:8px; font-family:var(--mono); font-size:13px;
}
.clip-modal-box .clip-actions {
    display:flex; gap:8px; margin-top:18px; justify-content:flex-end;
}
.clip-modal-box .clip-actions button {
    padding:8px 18px; border-radius:8px; font-family:var(--mono); font-size:12px;
    cursor:pointer; transition:all 0.15s;
}
.clip-modal-box .clip-cancel {
    background:none; border:1px solid var(--green-border); color:var(--green);
}
.clip-modal-box .clip-cancel:hover { border-color:var(--green-border-hover); }
.clip-modal-box .clip-go {
    background:var(--green); border:1px solid var(--green); color:var(--black); font-weight:700;
}
.clip-modal-box .clip-go:hover { box-shadow:0 4px 14px rgba(0,240,96,0.2); }
.clip-modal-box .clip-status {
    margin-top:12px; font-size:12px; color:var(--green-dim);
}

/* ======== MEMORY VIEW ======== */
.memory-view {
    flex-direction: column;
    overflow: hidden;
}

.memory-toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 24px;
    border-bottom: 1px solid var(--green-border);
}
.memory-toolbar input {
    flex: 1;
    max-width: 500px;
}
.memory-toolbar .stats {
    font-size: 14px;
    color: var(--green);
    margin-left: auto;
}

.memory-body {
    display: flex;
    flex: 1;
    min-height: 0;
}

/* Memory list (left panel) */
.memory-list-panel {
    width: 380px;
    min-width: 380px;
    border-right: 1px solid var(--green-border);
    overflow-y: auto;
    padding: 8px 8px 48px;
}

.memory-card {
    padding: 14px 16px;
    border: 1px solid transparent;
    border-radius: 12px;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
    margin-bottom: 4px;
}
.memory-card:hover { border-color: var(--green-border); background: var(--green-hover); }
.memory-card.active { border-color: var(--green-border-hover); background: var(--green-hover); border-left: 3px solid var(--green); }

.memory-card .card-title {
    font-size: 14px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-bottom: 6px;
    padding-right: 80px;
}
.memory-card .card-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11px;
    color: var(--green-dim);
}
.memory-card .card-meta .pill {
    background: rgba(0,240,96,0.08);
    border: 1px solid var(--green-border);
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 10px;
    font-weight: 600;
    color: var(--green);
}
.memory-card .card-meta .yt-icon {
    color: #FF0000;
    font-weight: 700;
    font-size: 10px;
}
.memory-card { position: relative; }
.memory-card .card-actions {
    position:absolute; top:10px; right:8px;
    display:flex; flex-direction:row; align-items:center; gap:2px;
    opacity:0; transition:opacity 0.15s;
}
.memory-card:hover .card-actions { opacity:0.7; }
.memory-card .card-actions button {
    background:none; border:none; cursor:pointer;
    padding:4px; line-height:1;
    display:flex; align-items:center; justify-content:center;
}
.memory-card .card-actions button:hover { opacity:1; }
.memory-card .card-actions svg { width:14px; height:14px; }

.memory-empty {
    padding: 40px 20px;
    text-align: center;
    color: var(--green-dim);
    font-size: 14px;
}

/* Memory detail (right panel) */
.memory-detail-panel {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    overflow: hidden;
}

.detail-placeholder {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--green-dim);
    font-size: 16px;
}

.detail-header {
    padding: 20px 24px;
    border-bottom: 1px solid var(--green-border);
}
.detail-header h2 {
    font-size: 20px;
    font-weight: 700;
    margin-bottom: 10px;
    letter-spacing: -0.3px;
}
.detail-meta {
    display: flex;
    align-items: center;
    gap: 16px;
    font-size: 12px;
    color: var(--green-dim);
    flex-wrap: wrap;
}
.detail-meta a {
    color: var(--green);
    text-decoration: none;
}
.detail-meta a:hover { text-decoration: underline; }

.detail-actions {
    display: flex;
    gap: 8px;
    margin-top: 12px;
}
.detail-actions button {
    padding: 6px 16px;
    background: var(--black);
    color: var(--green);
    border: 1px solid var(--green-border);
    font-family: var(--sans);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    border-radius: 8px;
    transition: border-color 0.15s, background 0.15s;
}
.detail-actions button:hover {
    border-color: var(--green-border-hover);
    background: var(--green-hover);
}

.detail-transcript {
    flex: 1;
    overflow-y: auto;
    padding: 16px 24px;
}
.detail-transcript .seg-row {
    display: flex;
    gap: 16px;
    padding: 8px 0;
    border-bottom: 1px solid var(--green-border);
    transition: background 0.1s;
}
.detail-transcript .seg-row:hover {
    background: var(--green-hover);
}
.detail-transcript .seg-ts {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--green-dim);
    white-space: nowrap;
    min-width: 50px;
    padding-top: 2px;
}
.detail-transcript .seg-ts a {
    color: var(--green);
    text-decoration: none;
}
.detail-transcript .seg-ts a:hover {
    text-decoration: underline;
}
.detail-transcript .seg-text {
    font-size: 14px;
    line-height: 1.6;
    color: var(--green);
}

/* Memory search results in detail panel */
.memory-search-results .sr-item {
    padding: 12px 0;
    border-bottom: 1px solid var(--green-border);
    cursor: pointer;
    transition: background 0.1s;
}
.memory-search-results .sr-item:hover {
    background: var(--green-hover);
}
.memory-search-results .sr-title {
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 4px;
}
.memory-search-results .sr-text {
    font-size: 13px;
    line-height: 1.5;
}
.memory-search-results .sr-text .hl {
    color: #FFFFFF;
    font-weight: 700;
}
.memory-search-results .sr-ts {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--green-dim);
    margin-top: 4px;
}
</style>
</head>
<body>

<!-- Top Navigation -->
<div class="top-nav">
    <span class="brand">Augent</span>
    <button class="nav-btn active" onclick="switchView('search', this)">Search</button>
    <button class="nav-btn" onclick="switchView('memory', this)">Memory</button>
</div>

<!-- ============ SEARCH VIEW ============ -->
<div class="view search-view active" id="view-search">
    <div class="sidebar">
        <div>
            <label>Audio File</label>
            <div class="upload-zone" id="uploadZone">
                <input type="file" id="fileInput" accept="audio/*,video/*,.mp3,.wav,.ogg,.flac,.m4a,.webm,.mp4,.aac,.wma,.opus">
                <button class="clear-btn" id="clearFileBtn" onclick="event.stopPropagation(); clearFile()" title="Clear file"></button>
                <div class="icon">&#x2B06;</div>
                <div class="label" id="uploadLabel">Drop audio file or click to upload</div>
            </div>
        </div>

        <div>
            <label>URL</label>
            <div class="url-wrap" id="urlWrap">
                <input type="text" id="audioUrl" placeholder="https://youtube.com/watch?v=...">
                <button class="clear-btn" onclick="clearUrl()" title="Clear URL"></button>
            </div>
            <div class="hint">Or paste a video/audio URL instead of uploading</div>
            <div class="waveform-wrap" id="waveformWrap">
                <div id="waveform"></div>
                <div class="wave-controls">
                    <button class="wave-btn" id="skipStartBtn" onclick="waveSkipStart()" title="Back to start">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="19 20 9 12 19 4"/><line x1="5" y1="4" x2="5" y2="20"/></svg>
                    </button>
                    <button class="wave-btn" id="playBtn" onclick="togglePlay()" title="Play / Pause">&#9654;</button>
                    <button class="wave-btn" id="skipEndBtn" onclick="waveSkipEnd()" title="Skip to end">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="5 4 15 12 5 20"/><line x1="19" y1="4" x2="19" y2="20"/></svg>
                    </button>
                    <span class="wave-time" id="waveTime">0:00 / 0:00</span>
                    <div class="wave-volume">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>
                        <input type="range" id="volumeSlider" min="0" max="100" value="80" oninput="setVolume(this.value)">
                    </div>
                </div>
            </div>
        </div>

        <div>
            <label>Keywords</label>
            <textarea id="keywords" placeholder="wormhole, open source, workflow"></textarea>
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
            <strong>Tips:</strong>
            <span class="tip-line">&#183; Paste a YouTube or video URL to download audio directly</span>
            <span class="tip-line">&#183; Results stored in memory for instant re-search</span>
            <span class="tip-line">&#183; Open multiple tabs for parallel processing</span>
        </div>
    </div>

    <div class="main">
        <div class="log-box">
            <div class="log-banner">
                <img src="/static/banner.png" alt="AUGENT" class="log-banner-img">
                <div class="log-tagline">Web UI v{{AUGENT_VERSION}}</div>
            </div>
            <div class="log-text" id="logBox"></div>
        </div>

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
            <div class="spinner-wrap hidden" id="spinnerWrap">
                <svg class="wormhole-spinner" viewBox="0 0 28 28">
                    <circle cx="14" cy="14" r="12" stroke-width="2" stroke-dasharray="20 48" opacity="0.3"/>
                    <circle cx="14" cy="14" r="8" stroke-width="1.5" stroke-dasharray="12 38" opacity="0.5" style="animation-direction:reverse"/>
                    <circle cx="14" cy="14" r="4" stroke-width="1" stroke-dasharray="6 20" opacity="0.8"/>
                </svg>
                <span class="spinner-label" id="spinnerLabel"></span>
            </div>
            <div class="progress-bar-wrap hidden" id="progressWrap">
                <div class="progress-bar-track"><div class="progress-bar-fill" id="progressFill"></div></div>
                <div class="progress-bar-label" id="progressLabel"></div>
            </div>
        </div>

        <div class="tab-panel" id="panel-json">
            <div class="json-box" id="jsonBox">{}</div>
        </div>
    </div>
</div>

<!-- ============ MEMORY VIEW ============ -->
<div class="view memory-view" id="view-memory">
    <div class="memory-toolbar">
        <input type="text" id="memoryQuery" placeholder="Search across all memories...">
        <div class="stats" id="memoryStats"></div>
    </div>
    <div class="memory-body">
        <div class="memory-list-panel" id="memoryListPanel">
            <div class="memory-empty" id="memoryEmpty">Loading...</div>
        </div>
        <div class="memory-detail-panel" id="memoryDetailPanel">
            <div class="detail-placeholder">Select a transcription to view</div>
        </div>
    </div>
</div>

<script>
/* ============ GLOBALS ============ */
let uploadedFile = null;
let wavesurfer = null;
let currentCacheKey = null;
let lastGrouped = null;
let lastSourceUrl = '';

/* ============ VIEW SWITCHING ============ */
function switchView(name, btn) {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById('view-' + name).classList.add('active');
    if (btn) btn.classList.add('active');
    if (name === 'memory') loadMemoryList();
}

/* ============ SEARCH VIEW ============ */
const fileInput = document.getElementById('fileInput');
const uploadZone = document.getElementById('uploadZone');
const uploadLabel = document.getElementById('uploadLabel');
const waveformWrap = document.getElementById('waveformWrap');

fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) setFile(file);
});

uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.classList.add('dragover'); });
uploadZone.addEventListener('dragleave', () => { uploadZone.classList.remove('dragover'); });
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
    document.getElementById('audioUrl').value = '';
    document.getElementById('urlWrap').classList.remove('has-url');
    loadWaveform(URL.createObjectURL(file));
    saveState();
}

function clearFile() {
    uploadedFile = null;
    memoryCacheKey = null;
    fileInput.value = '';
    uploadLabel.textContent = 'Drop audio file or click to upload';
    uploadZone.classList.remove('has-file');
    if (wavesurfer) { wavesurfer.destroy(); wavesurfer = null; }
    waveformWrap.classList.remove('visible');
    saveState();
}

function clearUrl() {
    document.getElementById('audioUrl').value = '';
    document.getElementById('urlWrap').classList.remove('has-url');
    if (wavesurfer) { wavesurfer.destroy(); wavesurfer = null; }
    waveformWrap.classList.remove('visible');
    saveState();
}

// Track URL input changes for clear button visibility
document.getElementById('audioUrl').addEventListener('input', function() {
    document.getElementById('urlWrap').classList.toggle('has-url', !!this.value.trim());
    saveState();
});

let memoryCacheKey = null;

function searchFromMemory(cardEl) {
    const cacheKey = cardEl.dataset.key;
    const title = cardEl.dataset.title;

    // Switch to search view
    switchView('search', document.querySelector('.nav-btn'));

    // Set memory search mode
    clearFile();
    clearUrl();
    memoryCacheKey = cacheKey;
    uploadLabel.textContent = '📁 ' + title;
    uploadZone.classList.add('has-file');

    // Focus keywords
    document.getElementById('keywords').focus();
}

function loadWaveform(url) {
    if (wavesurfer) { wavesurfer.destroy(); wavesurfer = null; }
    waveformWrap.classList.add('visible');

    wavesurfer = WaveSurfer.create({
        container: '#waveform', height: 48,
        waveColor: '#1a1a1a', progressColor: '#00F060',
        cursorColor: '#00F060', cursorWidth: 2,
        barWidth: 2, barGap: 1, barRadius: 2,
        normalize: true, backend: 'WebAudio',
    });

    wavesurfer.load(url);
    wavesurfer.setVolume(document.getElementById('volumeSlider').value / 100);

    const timeEl = document.getElementById('waveTime');
    const playBtn = document.getElementById('playBtn');

    wavesurfer.on('ready', () => {
        timeEl.textContent = '0:00 / ' + fmtTime(wavesurfer.getDuration());
    });
    wavesurfer.on('audioprocess', () => {
        timeEl.textContent = fmtTime(wavesurfer.getCurrentTime()) + ' / ' + fmtTime(wavesurfer.getDuration());
    });
    wavesurfer.on('seeking', () => {
        timeEl.textContent = fmtTime(wavesurfer.getCurrentTime()) + ' / ' + fmtTime(wavesurfer.getDuration());
    });
    wavesurfer.on('play', () => { playBtn.innerHTML = '&#9646;&#9646;'; });
    wavesurfer.on('pause', () => { playBtn.innerHTML = '&#9654;'; });
    wavesurfer.on('finish', () => { playBtn.innerHTML = '&#9654;'; });
}

function togglePlay() { if (wavesurfer) wavesurfer.playPause(); }
function waveSkipStart() { if (wavesurfer) wavesurfer.seekTo(0); }
function waveSkipEnd() { if (wavesurfer) wavesurfer.seekTo(1); }
function setVolume(val) { if (wavesurfer) wavesurfer.setVolume(val / 100); }

function switchTab(name, btn) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelector('#panel-' + name).classList.add('active');
    btn.classList.add('active');
}

async function startSearch() {
    const audioUrl = document.getElementById('audioUrl').value.trim();
    const hasFile = !!uploadedFile;
    const hasUrl = !!audioUrl;
    const hasMemory = !!memoryCacheKey;

    if (!hasFile && !hasUrl && !hasMemory) {
        appendLog('Upload an audio file or paste a URL');
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
    logBox.innerHTML = '';
    resultsContent.innerHTML = '<p>Starting...</p>';
    jsonBox.textContent = '{}';
    exportBar.classList.remove('visible');
    hideProgress(); hideSpinner();

    // Memory mode: search stored transcription directly
    if (hasMemory && !hasFile && !hasUrl) {
        btn.textContent = 'SEARCHING...';
        try {
            const resp = await fetch('/api/search-memory', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({cache_key: memoryCacheKey, keywords: keywords})
            });
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
                const {done, value} = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, {stream: true});
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = JSON.parse(line.slice(6));
                        if (data.type === 'log') appendLog(data.text);
                        else if (data.type === 'box') appendBox(data.lines, data.banner || false);
                        else if (data.type === 'status') resultsContent.innerHTML = '<p>' + data.text + '</p>';
                        else if (data.type === 'btn_text') btn.textContent = data.text;
                        else if (data.type === 'audio_url') loadWaveform(data.url);
                        else if (data.type === 'results') {
                            hideProgress(); hideSpinner();
                            lastGrouped = data.grouped;
                            lastSourceUrl = data.source_url || '';
                            renderResults(data.grouped, data.total, lastSourceUrl);
                            jsonBox.textContent = JSON.stringify(data.grouped, null, 2);
                            exportBar.classList.add('visible');
                            loadMemoryList();
                        }
                    }
                }
            }
        } catch (err) {
            appendLog('Error: ' + err.message);
            resultsContent.innerHTML = '<p>Error: ' + err.message + '</p>';
        }
        hideProgress(); hideSpinner();
        btn.disabled = false;
        btn.textContent = 'SEARCH';
        return;
    }

    // URL mode: download first
    if (hasUrl && !hasFile) {
        btn.textContent = 'DOWNLOADING...';
        appendLog('Downloading audio from URL...');
        try {
            const resp = await fetch('/api/download', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({url: audioUrl, model_size: model, keywords: keywords})
            });
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
                const {done, value} = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, {stream: true});
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = JSON.parse(line.slice(6));
                        if (data.type === 'log') appendLog(data.text);
                        else if (data.type === 'box') appendBox(data.lines, data.banner || false);
                        else if (data.type === 'status') resultsContent.innerHTML = '<p>' + data.text + '</p>';
                        else if (data.type === 'btn_text') btn.textContent = data.text;
                        else if (data.type === 'progress') showProgress(data.pct, data.label);
                        else if (data.type === 'spinner') showSpinner(data.label);
                        else if (data.type === 'audio_url') loadWaveform(data.url);
                        else if (data.type === 'results') {
                            hideProgress(); hideSpinner();
                            lastGrouped = data.grouped;
                            lastSourceUrl = data.source_url || '';
                            renderResults(data.grouped, data.total, lastSourceUrl);
                            jsonBox.textContent = JSON.stringify(data.grouped, null, 2);
                            exportBar.classList.add('visible');
                            loadMemoryList();
                        }
                    }
                }
            }
        } catch (err) {
            appendLog('Error: ' + err.message);
            resultsContent.innerHTML = '<p>Error: ' + err.message + '</p>';
        }
        hideProgress(); hideSpinner();
        btn.disabled = false;
        btn.textContent = 'SEARCH';
        return;
    }

    // File upload mode
    btn.textContent = 'SEARCHING...';
    const formData = new FormData();
    formData.append('file', uploadedFile);
    formData.append('keywords', keywords);
    formData.append('model_size', model);

    try {
        const response = await fetch('/api/search', { method: 'POST', body: formData });
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, {stream: true});
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.slice(6));
                    if (data.type === 'log') appendLog(data.text);
                    else if (data.type === 'box') appendBox(data.lines, data.banner || false);
                    else if (data.type === 'status') resultsContent.innerHTML = '<p>' + data.text + '</p>';
                    else if (data.type === 'btn_text') btn.textContent = data.text;
                    else if (data.type === 'progress') showProgress(data.pct, data.label);
                    else if (data.type === 'spinner') showSpinner(data.label);
                    else if (data.type === 'results') {
                        hideProgress(); hideSpinner();
                        lastGrouped = data.grouped;
                        lastSourceUrl = data.source_url || '';
                        renderResults(data.grouped, data.total, lastSourceUrl);
                        jsonBox.textContent = JSON.stringify(data.grouped, null, 2);
                        exportBar.classList.add('visible');
                        loadMemoryList();
                    }
                }
            }
        }
    } catch (err) {
        appendLog('Error: ' + err.message);
        resultsContent.innerHTML = '<p>Error: ' + err.message + '</p>';
    }

    hideProgress(); hideSpinner();
    btn.disabled = false;
    btn.textContent = 'SEARCH';
}

function appendLog(text) {
    const logBox = document.getElementById('logBox');
    const line = document.createTextNode(text + '\n');
    logBox.appendChild(line);
    logBox.parentElement.scrollTop = logBox.parentElement.scrollHeight;
}
function appendBox(lines, showBanner) {
    const logBox = document.getElementById('logBox');
    const container = document.createElement('div');
    container.style.cssText = 'margin:8px 0;display:inline-block;';
    const box = document.createElement('div');
    box.style.cssText = 'border:1px solid var(--green);border-radius:6px;padding:8px 14px;white-space:pre;';
    box.textContent = lines.join('\n');
    if (showBanner) {
        const bannerWrap = document.createElement('div');
        bannerWrap.style.cssText = 'text-align:center;margin-bottom:6px;';
        const img = document.createElement('img');
        img.src = '/static/banner.png';
        img.alt = 'AUGENT';
        img.style.cssText = 'width:180px;height:auto;image-rendering:-webkit-optimize-contrast;pointer-events:none;-webkit-user-drag:none;';
        bannerWrap.appendChild(img);
        container.appendChild(bannerWrap);
    }
    container.appendChild(box);
    logBox.appendChild(container);
    logBox.appendChild(document.createTextNode('\n'));
    logBox.parentElement.scrollTop = logBox.parentElement.scrollHeight;
}

function showProgress(pct, label) {
    hideSpinner();
    const wrap = document.getElementById('progressWrap');
    const fill = document.getElementById('progressFill');
    const lbl = document.getElementById('progressLabel');
    wrap.classList.remove('hidden');
    fill.style.width = pct + '%';
    lbl.textContent = label || '';
}

function hideProgress() {
    const wrap = document.getElementById('progressWrap');
    const fill = document.getElementById('progressFill');
    wrap.classList.add('hidden');
    fill.style.width = '0%';
}

function showSpinner(label) {
    hideProgress();
    const wrap = document.getElementById('spinnerWrap');
    const lbl = document.getElementById('spinnerLabel');
    wrap.classList.remove('hidden');
    lbl.textContent = label || '';
}

function hideSpinner() {
    document.getElementById('spinnerWrap').classList.add('hidden');
}

function renderResults(grouped, total, sourceUrl) {
    const el = document.getElementById('resultsContent');
    if (total === 0) { el.innerHTML = '<h3>No matches found.</h3>'; return; }
    const hasYt = sourceUrl && sourceUrl.includes('youtu');
    let html = '<h3>Found ' + total + ' matches</h3>';
    if (!hasYt && total > 0) {
        html += '<div class="yt-hint">' +
            '<span>Know the YouTube URL?</span>' +
            '<input type="text" id="ytLinkInput" placeholder="https://youtube.com/watch?v=...">' +
            '<button onclick="relinkTimestamps()">Link timestamps</button>' +
            '</div>';
    }
    for (const [kw, matches] of Object.entries(grouped)) {
        html += '<h4>' + escHtml(kw) + ' (' + matches.length + ')</h4>';
        html += '<table><thead><tr><th>Time</th><th>Context</th></tr></thead><tbody>';
        for (const m of matches) {
            const snippet = highlightKeyword(escHtml(m.snippet), kw);
            let tsCell;
            if (m.youtube_link) {
                tsCell = '<a href="' + escHtml(m.youtube_link) + '" target="_blank" rel="noopener">' + escHtml(m.timestamp) + '</a>';
            } else {
                tsCell = escHtml(m.timestamp);
            }
            // Clip export button
            const clipBtn = sourceUrl ?
                '<button class="clip-btn" onclick="openClipModal(\'' + escHtml(sourceUrl) + '\',' + (m.timestamp_seconds || 0) + ',\'' + escHtml(kw) + '\')" title="Export video clip"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/></svg></button>' : '';
            html += '<tr><td>' + tsCell + clipBtn + '</td><td>' + snippet + '</td></tr>';
        }
        html += '</tbody></table>';
    }
    el.innerHTML = html;
}

function relinkTimestamps() {
    const input = document.getElementById('ytLinkInput');
    if (!input) return;
    const url = input.value.trim();
    if (!url) { input.focus(); return; }
    const re = /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})/;
    const match = url.match(re);
    if (!match) { alert('Not a valid YouTube URL'); input.focus(); return; }
    const videoId = match[1];
    for (const [kw, matches] of Object.entries(lastGrouped)) {
        for (const m of matches) {
            m.youtube_link = 'https://youtube.com/watch?v=' + videoId + '&t=' + Math.floor(m.timestamp_seconds);
        }
    }
    lastSourceUrl = url;
    renderResults(lastGrouped, Object.values(lastGrouped).reduce((a, b) => a + b.length, 0), url);
    appendLog('  [info] YouTube timestamps linked');
}

function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function highlightKeyword(snippet, keyword) {
    const clean = snippet.replace(/\.\.\./g, '').replace(/\*\*/g, '').trim();
    const re = new RegExp('(' + keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
    return clean.replace(re, '<span class="match-word">$1</span>');
}

function exportAs(format) {
    const keywords = document.getElementById('keywords').value.trim();
    window.location.href = '/api/export?format=' + format + '&keywords=' + encodeURIComponent(keywords);
}

/* ============ CLIP EXPORT ============ */
function fmtSec(s) {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return m + ':' + String(sec).padStart(2, '0');
}

function parseMmSs(str) {
    const parts = str.trim().split(':');
    if (parts.length === 2) return parseInt(parts[0]) * 60 + parseInt(parts[1]);
    if (parts.length === 3) return parseInt(parts[0]) * 3600 + parseInt(parts[1]) * 60 + parseInt(parts[2]);
    return parseFloat(str) || 0;
}

function openClipModal(url, timestampSec, keyword) {
    const padding = 10;
    const start = Math.max(0, timestampSec - padding);
    const end = timestampSec + padding;

    const modal = document.createElement('div');
    modal.className = 'clip-modal';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    modal.innerHTML =
        '<div class="clip-modal-box">' +
        '<h3>Export Video Clip</h3>' +
        '<label>Source</label>' +
        '<input type="text" id="clipUrl" value="' + escHtml(url) + '" readonly style="opacity:0.6;">' +
        '<label>Keyword match at ' + fmtSec(timestampSec) + ' (' + escHtml(keyword) + ')</label>' +
        '<div style="display:flex;gap:12px;">' +
        '<div style="flex:1;"><label>Start</label><input type="text" id="clipStart" value="' + fmtSec(start) + '"></div>' +
        '<div style="flex:1;"><label>End</label><input type="text" id="clipEnd" value="' + fmtSec(end) + '"></div>' +
        '</div>' +
        '<div class="clip-actions">' +
        '<button class="clip-cancel" onclick="this.closest(\'.clip-modal\').remove()">Cancel</button>' +
        '<button class="clip-go" onclick="doClipExport(this.closest(\'.clip-modal\'))">Export MP4</button>' +
        '</div>' +
        '<div class="clip-status" id="clipStatus"></div>' +
        '</div>';
    document.body.appendChild(modal);
    document.getElementById('clipStart').focus();
}

async function doClipExport(modal) {
    const url = document.getElementById('clipUrl').value;
    const start = parseMmSs(document.getElementById('clipStart').value);
    const end = parseMmSs(document.getElementById('clipEnd').value);
    const status = document.getElementById('clipStatus');
    const goBtn = modal.querySelector('.clip-go');

    if (end <= start) { status.textContent = 'End must be after start'; return; }

    goBtn.disabled = true;
    goBtn.textContent = 'Exporting...';
    status.textContent = 'Downloading clip (' + fmtSec(start) + ' → ' + fmtSec(end) + ')...';

    try {
        const resp = await fetch('/api/clip-export', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url, start, end})
        });
        const data = await resp.json();
        if (data.error) {
            status.textContent = 'Error: ' + data.error;
            goBtn.disabled = false;
            goBtn.textContent = 'Export MP4';
        } else {
            status.innerHTML = 'Saved: <strong>' + escHtml(data.filename) + '</strong> (' + data.file_size_mb + ' MB, ' + data.duration_formatted + ')';
            goBtn.textContent = 'Done!';
            setTimeout(() => modal.remove(), 3000);
        }
    } catch (err) {
        status.textContent = 'Error: ' + err.message;
        goBtn.disabled = false;
        goBtn.textContent = 'Export MP4';
    }
}

/* ============ MEMORY VIEW ============ */
let memoryDebounce = null;
document.getElementById('memoryQuery').addEventListener('input', (e) => {
    clearTimeout(memoryDebounce);
    memoryDebounce = setTimeout(() => {
        const q = e.target.value.trim();
        if (q.length >= 2) searchMemory(q);
        else loadMemoryList();
    }, 300);
});

async function loadMemoryList() {
    const panel = document.getElementById('memoryListPanel');
    const statsEl = document.getElementById('memoryStats');
    try {
        const resp = await fetch('/api/memory/list');
        const data = await resp.json();
        const items = data.items || [];
        statsEl.textContent = items.length + ' transcription' + (items.length !== 1 ? 's' : '') + ' in memory';

        if (items.length === 0) {
            panel.innerHTML = '<div class="memory-empty">No transcriptions in memory yet.<br>Transcribe audio to build your library.</div>';
            return;
        }

        let html = '';
        for (const item of items) {
            const isYt = item.source_url && item.source_url.includes('youtu');
            const ytBadge = isYt ? '<span class="yt-icon">YT</span>' : '';
            html += '<div class="memory-card" data-key="' + escHtml(item.cache_key) + '" data-source-url="' + escHtml(item.source_url || '') + '" data-file-path="' + escHtml(item.file_path || '') + '" data-title="' + escHtml(item.title) + '" onclick="loadMemoryDetail(\'' + escHtml(item.cache_key) + '\', this)">';
            html += '<div class="card-actions">';
            html += '<button class="search-action" onclick="event.stopPropagation(); searchFromMemory(this.closest(\'.memory-card\'))" title="Search this audio"><svg viewBox="0 0 24 24" fill="none" stroke="#00F060" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></button>';
            html += '<button onclick="event.stopPropagation(); revealMemory(\'' + escHtml(item.cache_key) + '\')" title="Show Audio in Finder"><svg viewBox="0 0 24 24" fill="none" stroke="#00F060" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></button>';
            html += '<button onclick="event.stopPropagation(); revealTranscript(\'' + escHtml(item.cache_key) + '\')" title="Show Transcript in Finder"><svg viewBox="0 0 24 24" fill="none" stroke="#00F060" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg></button>';
            html += '<button onclick="event.stopPropagation(); deleteMemory(\'' + escHtml(item.cache_key) + '\', this)" title="Delete from memory"><svg viewBox="0 0 24 24" fill="none" stroke="#00F060" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg></button>';
            html += '</div>';
            html += '<div class="card-title">' + escHtml(item.title) + '</div>';
            html += '<div class="card-meta">';
            html += '<span>' + escHtml(item.duration_formatted) + '</span>';
            html += '<span class="pill">' + escHtml(item.model_size) + '</span>';
            html += ytBadge;
            html += '<span>' + escHtml(item.date) + '</span>';
            html += '</div></div>';
        }
        panel.innerHTML = html;
    } catch (err) {
        panel.innerHTML = '<div class="memory-empty">Error loading memories</div>';
    }
}

async function loadMemoryDetail(cacheKey, cardEl) {
    currentCacheKey = cacheKey;

    // Highlight active card
    document.querySelectorAll('.memory-card').forEach(c => c.classList.remove('active'));
    if (cardEl) cardEl.classList.add('active');

    const panel = document.getElementById('memoryDetailPanel');
    panel.innerHTML = '<div class="detail-placeholder">Loading...</div>';

    try {
        const resp = await fetch('/api/memory/detail/' + encodeURIComponent(cacheKey));
        if (!resp.ok) throw new Error('Not found');
        const d = await resp.json();

        let metaParts = [
            escHtml(d.duration_formatted),
            escHtml(d.language || ''),
            escHtml(d.model_size),
            escHtml(d.date),
        ].filter(Boolean);

        let sourceHtml = '';
        if (d.source_url) {
            sourceHtml = ' &middot; <a href="' + escHtml(d.source_url) + '" target="_blank" rel="noopener">Source</a>';
        }

        let segsHtml = '';
        for (const seg of (d.segments || [])) {
            const ts = seg.timestamp || '';
            let tsHtml;
            if (seg.youtube_link) {
                tsHtml = '<a href="' + escHtml(seg.youtube_link) + '" target="_blank" rel="noopener">' + escHtml(ts) + '</a>';
            } else {
                tsHtml = escHtml(ts);
            }
            segsHtml += '<div class="seg-row"><div class="seg-ts">' + tsHtml + '</div><div class="seg-text">' + escHtml(seg.text) + '</div></div>';
        }

        if (!segsHtml && d.text) {
            segsHtml = '<div style="padding:12px 0;font-size:14px;line-height:1.8;">' + escHtml(d.text) + '</div>';
        }

        panel.innerHTML = '<div class="detail-header">' +
            '<h2>' + escHtml(d.title) + '</h2>' +
            '<div class="detail-meta">' + metaParts.join(' &middot; ') + sourceHtml + '</div>' +
            '<div class="detail-actions">' +
            '<button onclick="shareTranscript()">Share as HTML</button>' +
            (d.file_path ? '<button onclick="showInFinder()">Show Audio</button>' : '') +
            '<button onclick="showTranscript()">Show Transcript</button>' +
            '</div>' +
            '</div>' +
            '<div class="detail-transcript">' + segsHtml + '</div>';
    } catch (err) {
        panel.innerHTML = '<div class="detail-placeholder">Error loading transcript</div>';
    }
}

async function searchMemory(query) {
    const panel = document.getElementById('memoryListPanel');
    const detailPanel = document.getElementById('memoryDetailPanel');

    try {
        const resp = await fetch('/api/memory/search?q=' + encodeURIComponent(query) + '&limit=50');
        const data = await resp.json();
        const results = data.results || [];

        if (results.length === 0) {
            panel.innerHTML = '<div class="memory-empty">No matches for "' + escHtml(query) + '"</div>';
            return;
        }

        document.getElementById('memoryStats').textContent = results.length + ' match' + (results.length !== 1 ? 'es' : '');

        let html = '<div class="memory-search-results">';
        for (const r of results) {
            const text = highlightInText(r.text, query);
            html += '<div class="sr-item" onclick="loadMemoryDetail(\'' + escHtml(r.cache_key) + '\', null)">';
            html += '<div class="sr-title">' + escHtml(r.title) + '</div>';
            html += '<div class="sr-text">' + text + '</div>';
            html += '<div class="sr-ts">' + escHtml(r.timestamp) + '</div>';
            html += '</div>';
        }
        html += '</div>';
        panel.innerHTML = html;
    } catch (err) {
        panel.innerHTML = '<div class="memory-empty">Search error</div>';
    }
}

function highlightInText(text, query) {
    const safe = escHtml(text);
    const re = new RegExp('(' + query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
    return safe.replace(re, '<span class="hl">$1</span>');
}

function shareTranscript() {
    if (!currentCacheKey) return;
    window.location.href = '/api/memory/share/' + encodeURIComponent(currentCacheKey);
}

async function showInFinder() {
    if (!currentCacheKey) return;
    await revealMemory(currentCacheKey);
}

async function revealMemory(cacheKey) {
    try {
        const resp = await fetch('/api/memory/reveal/' + encodeURIComponent(cacheKey), {method: 'POST'});
        if (!resp.ok) {
            const data = await resp.json();
            alert(data.error || 'Could not reveal file');
        }
    } catch (err) {
        alert('Could not connect to server');
    }
}

async function revealTranscript(cacheKey) {
    try {
        const resp = await fetch('/api/memory/reveal/' + encodeURIComponent(cacheKey) + '?target=transcript', {method: 'POST'});
        if (!resp.ok) {
            const data = await resp.json();
            alert(data.error || 'No transcript file found');
        }
    } catch (err) {
        alert('Could not connect to server');
    }
}

async function showTranscript() {
    if (!currentCacheKey) return;
    await revealTranscript(currentCacheKey);
}

async function deleteMemory(cacheKey, btnEl) {
    if (!confirm('Delete this transcription from memory? This cannot be undone.')) return;
    try {
        const resp = await fetch('/api/memory/' + encodeURIComponent(cacheKey), {method: 'DELETE'});
        if (resp.ok) {
            const card = btnEl.closest('.memory-card');
            if (card) card.remove();
            // Clear detail panel if we just deleted the active one
            if (currentCacheKey === cacheKey) {
                currentCacheKey = null;
                document.getElementById('memoryDetailPanel').innerHTML =
                    '<div class="detail-placeholder">Select a transcription to view</div>';
            }
            // Update stats count
            const remaining = document.querySelectorAll('.memory-card').length;
            document.getElementById('memoryStats').textContent =
                remaining + ' transcription' + (remaining !== 1 ? 's' : '') + ' in memory';
        } else {
            alert('Failed to delete');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

/* ============ STATE PERSISTENCE ============ */
function saveState() {
    try {
        sessionStorage.setItem('augent_state', JSON.stringify({
            keywords: document.getElementById('keywords').value,
            audioUrl: document.getElementById('audioUrl').value,
            model: document.getElementById('model').value,
        }));
    } catch(e) {}
}

function restoreState() {
    try {
        const raw = sessionStorage.getItem('augent_state');
        if (!raw) return;
        const s = JSON.parse(raw);
        if (s.keywords) document.getElementById('keywords').value = s.keywords;
        if (s.audioUrl) {
            document.getElementById('audioUrl').value = s.audioUrl;
            document.getElementById('urlWrap').classList.toggle('has-url', !!s.audioUrl);
        }
        if (s.model) document.getElementById('model').value = s.model;
    } catch(e) {}
}

// Save on input changes
document.getElementById('keywords').addEventListener('input', saveState);
document.getElementById('model').addEventListener('change', saveState);

// Restore on page load
restoreState();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# API Routes — Search (existing)
# ---------------------------------------------------------------------------


_audio_tokens: dict[str, str] = {}


def _register_audio(file_path: str) -> str:
    """Store a file path server-side and return an opaque token."""
    import secrets

    token = secrets.token_urlsafe(16)
    _audio_tokens[token] = os.path.realpath(file_path)
    return token


@app.get("/api/audio")
async def serve_audio(token: str = Query("")):
    """Serve a downloaded audio file by opaque token (no user-controlled paths)."""
    file_path = _audio_tokens.get(token, "")
    if not file_path or not pathlib.Path(file_path).is_file():
        return JSONResponse({"error": "File not found"}, status_code=404)
    import mimetypes

    mime = mimetypes.guess_type(file_path)[0] or "audio/mpeg"
    return Response(content=pathlib.Path(file_path).read_bytes(), media_type=mime)


@app.get("/static/banner.png")
async def serve_banner():
    banner_path = os.path.join(os.path.dirname(__file__), "augentbanner.png")
    with open(banner_path, "rb") as f:
        return Response(content=f.read(), media_type="image/png")


@app.get("/", response_class=HTMLResponse)
async def index():
    from . import __version__

    return HTML_PAGE.replace("{{AUGENT_VERSION}}", __version__)


@app.post("/api/search")
async def search_audio(
    file: UploadFile = File(...),  # noqa: B008
    keywords: str = Form(""),  # noqa: B008
    model_size: str = Form("tiny"),  # noqa: B008
):
    """Stream search results via SSE (file upload mode)."""

    async def event_stream():
        global _latest_results

        # Use original filename so memory stores a readable title
        safe_name = Path(file.filename).name if file.filename else "upload.tmp"
        tmp_path = os.path.join("/tmp", safe_name)
        content = await file.read()
        with open(tmp_path, "wb") as tmp:
            tmp.write(content)

        try:
            keyword_list = [k.strip().lower() for k in keywords.split(",") if k.strip()]
            if not keyword_list:
                yield f"data: {json.dumps({'type': 'log', 'text': 'No keywords provided'})}\n\n"
                return

            filename = file.filename or "uploaded"

            def send(type_, **kwargs):
                return f"data: {json.dumps({'type': type_, **kwargs})}\n\n"

            box_lines = [
                f"[augent] file: {filename}",
                f"[augent] keywords: {', '.join(keyword_list)}",
                f"[augent] model: {model_size}",
            ]
            yield send("box", lines=box_lines, banner=False)
            yield send("status", text="Starting...")

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
                yield send("spinner", label="Loading model...")

                model_cache = get_model_cache()
                model = model_cache.get(model_size)

                yield send("log", text="  [model] ready")
                yield send("log", text="")
                yield send("progress", pct=0, label="Transcribing — 0%")
                yield send("btn_text", text="TRANSCRIBING...")
                yield send("status", text="Transcribing audio...")

                transcribe_kwargs = {"word_timestamps": True, "vad_filter": True}
                segments_gen, info = model.transcribe(tmp_path, **transcribe_kwargs)

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

                    if duration > 0:
                        pct = min(int(segment.end / duration * 100), 100)
                        yield send(
                            "progress",
                            pct=pct,
                            label=f"Transcribing — {pct}%",
                        )

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

                    await asyncio.sleep(0)

                yield send("progress", pct=100, label="Transcription complete")

                try:
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
                    yield send("log", text="  [memory] saved to memory")
                except Exception as mem_err:
                    yield send("log", text=f"  [memory] save failed: {mem_err}")

            yield send("log", text="")
            yield send("log", text="  [search] finding matches...")
            yield send("btn_text", text="SEARCHING...")
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
            _lines = [f"[done] {len(matches)} matches found"]
            for kw in grouped:
                _lines.append(f"       {kw}: {len(grouped[kw])}")
            yield send("box", lines=_lines, banner=True)

            async with _latest_results_lock:
                _latest_results = {"grouped": grouped, "total": len(matches)}

            yield send("results", grouped=grouped, total=len(matches), source_url="")

        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/search-memory")
async def search_from_memory(request: Request):
    """Search a stored transcription by cache_key — no audio file needed."""
    body = await request.json()
    cache_key = body.get("cache_key", "")
    keywords_str = body.get("keywords", "")

    async def event_stream():
        global _latest_results

        def send(type_, **kwargs):
            return f"data: {json.dumps({'type': type_, **kwargs})}\n\n"

        keyword_list = [k.strip().lower() for k in keywords_str.split(",") if k.strip()]
        if not keyword_list:
            yield send("log", text="No keywords provided")
            return
        if not cache_key:
            yield send("log", text="No cache key provided")
            return

        memory = get_transcription_memory()
        entry = memory.get_by_cache_key(cache_key)
        if not entry:
            yield send("log", text="  [error] transcription not found in memory")
            return

        yield send(
            "box",
            lines=[
                f"[augent] title: {entry.title}",
                f"[augent] keywords: {', '.join(keyword_list)}",
                f"[augent] model: {entry.model_size}",
            ],
            banner=False,
        )

        yield send("log", text="  [memory] loaded from memory")
        yield send("log", text=f"  [info] duration: {format_time(entry.duration)}")
        yield send("log", text=f"  [info] language: {entry.language}")
        yield send("log", text="")

        # Load waveform if file still exists
        if entry.file_path and os.path.isfile(entry.file_path):
            audio_token = _register_audio(entry.file_path)
            yield send("audio_url", url=f"/api/audio?token={audio_token}")

        yield send("log", text="  [search] finding matches...")
        yield send("status", text="Searching...")

        searcher = KeywordSearcher(context_words=11)
        matches = searcher.search(entry.words, keyword_list)

        grouped = {}
        for m in matches:
            kw = m.keyword
            if kw not in grouped:
                grouped[kw] = []
            e = {
                "timestamp": m.timestamp,
                "timestamp_seconds": m.timestamp_seconds,
                "snippet": m.snippet,
            }
            if entry.source_url:
                yt_link = _youtube_timestamp_link(entry.source_url, m.timestamp_seconds)
                if yt_link:
                    e["youtube_link"] = yt_link
            grouped[kw].append(e)

        yield send("log", text="")
        _lines = [f"[done] {len(matches)} matches found"]
        for kw in grouped:
            _lines.append(f"       {kw}: {len(grouped[kw])}")
        yield send("box", lines=_lines, banner=True)

        async with _latest_results_lock:
            _latest_results = {"grouped": grouped, "total": len(matches)}

        yield send(
            "results",
            grouped=grouped,
            total=len(matches),
            source_url=entry.source_url or "",
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/download")
async def download_and_search(request: Request):
    """Download audio from URL, transcribe, and search — all streamed via SSE."""
    body = await request.json()
    url = body.get("url", "")
    model_size = body.get("model_size", "tiny")
    keywords_str = body.get("keywords", "")

    async def event_stream():
        global _latest_results

        def send(type_, **kwargs):
            return f"data: {json.dumps({'type': type_, **kwargs})}\n\n"

        keyword_list = [k.strip().lower() for k in keywords_str.split(",") if k.strip()]
        if not keyword_list:
            yield send("log", text="No keywords provided")
            return

        if not url:
            yield send("log", text="No URL provided")
            return

        # Handle file:// paths — search local audio directly
        local_path = None
        if url.startswith("file://"):
            local_path = url[7:]  # strip file://
            if not os.path.isfile(local_path):
                yield send("log", text=f"  [error] file not found: {local_path}")
                return

        display_url = os.path.basename(local_path) if local_path else url
        box_lines = [
            f"[augent] {'file' if local_path else 'url'}: {display_url}",
            f"[augent] keywords: {', '.join(keyword_list)}",
            f"[augent] model: {model_size}",
        ]
        yield send("box", lines=box_lines, banner=False)

        # Check if we already have this in memory
        memory = get_transcription_memory()
        stored_by_url = None
        if local_path:
            stored_by_url = memory.get(local_path, model_size)
        else:
            stored_by_url = memory.get_by_source_url(url, model_size)

        if stored_by_url:
            yield send("log", text="  [memory] loaded from memory")
            yield send(
                "log",
                text=f"  [info] duration: {format_time(stored_by_url.duration)}",
            )
            yield send("log", text="")
            yield send("status", text="Loaded from memory")

            all_words = stored_by_url.words
            searcher = KeywordSearcher(context_words=11)
            matches = searcher.search(all_words, keyword_list)

            grouped = {}
            for m in matches:
                kw = m.keyword
                if kw not in grouped:
                    grouped[kw] = []
                entry = {
                    "timestamp": m.timestamp,
                    "timestamp_seconds": m.timestamp_seconds,
                    "snippet": m.snippet,
                }
                yt_link = _youtube_timestamp_link(url, m.timestamp_seconds)
                if yt_link:
                    entry["youtube_link"] = yt_link
                grouped[kw].append(entry)

            _lines = [f"[done] {len(matches)} matches found"]
            for kw in grouped:
                _lines.append(f"       {kw}: {len(grouped[kw])}")
            yield send("box", lines=_lines, banner=True)

            async with _latest_results_lock:
                _latest_results = {"grouped": grouped, "total": len(matches)}

            yield send(
                "results",
                grouped=grouped,
                total=len(matches),
                source_url=url,
            )
            return

        # Local file path — skip download, go straight to transcribe
        if local_path:
            audio_path = local_path
            yield send("log", text=f"  [file] {os.path.basename(audio_path)}")
            audio_token = _register_audio(audio_path)
            yield send("audio_url", url=f"/api/audio?token={audio_token}")
            yield send("log", text="")

            memory = get_transcription_memory()
            stored = memory.get(audio_path, model_size)

            if stored:
                yield send("log", text="  [memory] loaded from memory")
                yield send(
                    "log", text=f"  [info] duration: {format_time(stored.duration)}"
                )
                yield send("log", text="")
                all_words = stored.words
            else:
                yield send("log", text=f"  [model] loading {model_size}...")
                yield send("spinner", label="Loading model...")
                model_cache = get_model_cache()
                model = model_cache.get(model_size)
                yield send("log", text="  [model] ready")
                yield send("log", text="")
                yield send("progress", pct=0, label="Transcribing — 0%")
                yield send("btn_text", text="TRANSCRIBING...")
                yield send("status", text="Transcribing audio...")

                transcribe_kwargs = {"word_timestamps": True, "vad_filter": True}
                segments_gen, info = model.transcribe(audio_path, **transcribe_kwargs)
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
                    if duration > 0:
                        pct = min(int(segment.end / duration * 100), 100)
                        yield send("progress", pct=pct, label=f"Transcribing — {pct}%")
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
                    await asyncio.sleep(0)

                yield send("progress", pct=100, label="Transcription complete")

                try:
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
                    yield send("log", text="  [memory] saved to memory")
                except Exception as mem_err:
                    yield send("log", text=f"  [memory] save failed: {mem_err}")

            yield send("log", text="")
            yield send("log", text="  [search] finding matches...")
            yield send("btn_text", text="SEARCHING...")
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
            _lines = [f"[done] {len(matches)} matches found"]
            for kw in grouped:
                _lines.append(f"       {kw}: {len(grouped[kw])}")
            yield send("box", lines=_lines, banner=True)

            async with _latest_results_lock:
                _latest_results = {"grouped": grouped, "total": len(matches)}

            yield send("results", grouped=grouped, total=len(matches), source_url="")
            return

        yield send("status", text="Downloading audio...")
        yield send("log", text="  [download] starting...")

        # Download audio using yt-dlp
        download_dir = tempfile.mkdtemp(prefix="augent_dl_", dir="/tmp")
        try:
            ytdlp = shutil.which(
                "yt-dlp", path="/opt/homebrew/bin:/usr/local/bin"
            ) or shutil.which("yt-dlp")
            if not ytdlp:
                yield send("log", text="  [error] yt-dlp not found")
                return

            cmd = [
                ytdlp,
                "-f",
                "bestaudio/best",
                "-x",
                "--concurrent-fragments",
                "4",
                "--no-playlist",
                "-o",
                f"{download_dir}/%(title)s.%(ext)s",
                "--print",
                "after_move:filepath",
            ]
            if shutil.which("aria2c"):
                cmd.extend(
                    [
                        "--downloader",
                        "aria2c",
                        "--downloader-args",
                        "aria2c:-x 16 -s 16 -k 1M",
                    ]
                )
            cmd.append(url)

            yield send("spinner", label="Downloading audio...")

            proc = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True
            )

            if proc.returncode != 0:
                yield send(
                    "log",
                    text=f"  [error] download failed: {proc.stderr.strip()[:200]}",
                )
                return

            output_lines = proc.stdout.strip().split("\n")
            audio_path = output_lines[-1] if output_lines else None

            if not audio_path or not os.path.exists(audio_path):
                yield send("log", text="  [error] downloaded file not found")
                return

            yield send(
                "log", text=f"  [download] complete: {os.path.basename(audio_path)}"
            )
            audio_token = _register_audio(audio_path)
            yield send(
                "audio_url",
                url=f"/api/audio?token={audio_token}",
            )
            yield send("log", text="")

            # Transcribe
            memory = get_transcription_memory()
            stored = memory.get(audio_path, model_size)

            if stored:
                yield send("log", text="  [memory] loaded from memory")
                yield send(
                    "log", text=f"  [info] duration: {format_time(stored.duration)}"
                )
                yield send("log", text="")
                all_words = stored.words
            else:
                yield send("log", text=f"  [model] loading {model_size}...")
                yield send("spinner", label="Loading model...")

                model_cache = get_model_cache()
                model = model_cache.get(model_size)

                yield send("log", text="  [model] ready")
                yield send("log", text="")
                yield send("progress", pct=0, label="Transcribing — 0%")
                yield send("btn_text", text="TRANSCRIBING...")
                yield send("status", text="Transcribing audio...")

                transcribe_kwargs = {"word_timestamps": True, "vad_filter": True}
                segments_gen, info = model.transcribe(audio_path, **transcribe_kwargs)

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

                    if duration > 0:
                        pct = min(int(segment.end / duration * 100), 100)
                        yield send(
                            "progress",
                            pct=pct,
                            label=f"Transcribing — {pct}%",
                        )

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

                    await asyncio.sleep(0)

                yield send("progress", pct=100, label="Transcription complete")

                try:
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
                        source_url=url,
                    )
                    yield send("log", text="  [memory] saved to memory")
                except Exception as mem_err:
                    yield send("log", text=f"  [memory] save failed: {mem_err}")
                # Persist YouTube URL by hash (survives restarts)
                if _extract_youtube_id(url):
                    memory.save_source_url(audio_path, url)

            # Search
            yield send("log", text="")
            yield send("log", text="  [search] finding matches...")
            yield send("btn_text", text="SEARCHING...")
            yield send("status", text="Searching...")

            searcher = KeywordSearcher(context_words=11)
            matches = searcher.search(all_words, keyword_list)

            grouped = {}
            for m in matches:
                kw = m.keyword
                if kw not in grouped:
                    grouped[kw] = []
                entry = {
                    "timestamp": m.timestamp,
                    "timestamp_seconds": m.timestamp_seconds,
                    "snippet": m.snippet,
                }
                yt_link = _youtube_timestamp_link(url, m.timestamp_seconds)
                if yt_link:
                    entry["youtube_link"] = yt_link
                grouped[kw].append(entry)

            yield send("log", text="")
            _lines = [f"[done] {len(matches)} matches found"]
            for kw in grouped:
                _lines.append(f"       {kw}: {len(grouped[kw])}")
            yield send("box", lines=_lines, banner=True)

            async with _latest_results_lock:
                _latest_results = {"grouped": grouped, "total": len(matches)}

            yield send(
                "results",
                grouped=grouped,
                total=len(matches),
                source_url=url,
            )

        except Exception as e:
            yield send("log", text=f"  [error] {str(e)}")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/clip-export")
async def clip_export(request: Request):
    """Export a video clip from a URL for a specific time range."""
    body = await request.json()
    url = body.get("url", "")
    start = body.get("start", 0)
    end = body.get("end", 0)

    if not url:
        return JSONResponse({"error": "No URL provided"})
    if end <= start:
        return JSONResponse({"error": "End must be after start"})

    ytdlp = shutil.which(
        "yt-dlp", path="/opt/homebrew/bin:/usr/local/bin"
    ) or shutil.which("yt-dlp")
    if not ytdlp:
        return JSONResponse({"error": "yt-dlp not found"})

    output_dir = os.path.expanduser("~/Desktop")

    def fmt_time(s):
        m, sec = divmod(int(s), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    section = f"*{fmt_time(start)}-{fmt_time(end)}"

    cmd = [
        ytdlp,
        "--download-sections",
        section,
        "--force-keyframes-at-cuts",
        "-f",
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        "--no-playlist",
        "-o",
        os.path.join(output_dir, "%(title)s_clip.%(ext)s"),
        "--print",
        "after_move:filepath",
        url,
    ]

    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=300
        )
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "Clip export timed out (5 min limit)"})

    if result.returncode != 0:
        error_msg = result.stderr.strip()[-200:] if result.stderr else "Unknown error"
        return JSONResponse({"error": f"yt-dlp failed: {error_msg}"})

    output_lines = result.stdout.strip().split("\n")
    clip_path = output_lines[-1] if output_lines else None

    if not clip_path or not os.path.exists(clip_path):
        return JSONResponse({"error": "Clip file not found after export"})

    file_size = os.path.getsize(clip_path)
    duration = end - start

    return JSONResponse(
        {
            "clip_path": clip_path,
            "filename": os.path.basename(clip_path),
            "duration": duration,
            "duration_formatted": f"{int(duration // 60)}:{int(duration % 60):02d}",
            "file_size_mb": round(file_size / (1024 * 1024), 2),
        }
    )


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
        lines = ["# Augent Search Results", f"**{results['total']} matches**", ""]
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


# ---------------------------------------------------------------------------
# API Routes — Memory
# ---------------------------------------------------------------------------


@app.get("/api/memory/list")
async def api_memory_list():
    """List all stored transcriptions."""
    memory = get_transcription_memory()
    items = memory.list_all()
    return JSONResponse({"items": items})


@app.get("/api/memory/detail/{cache_key:path}")
async def api_memory_detail(cache_key: str):
    """Get full transcript for a single entry."""
    memory = get_transcription_memory()
    entry = memory.get_by_cache_key(cache_key)
    if not entry:
        return JSONResponse({"error": "Not found"}, status_code=404)

    from datetime import datetime

    date_str = (
        datetime.fromtimestamp(entry.created_at).strftime("%Y-%m-%d %H:%M")
        if entry.created_at
        else ""
    )

    mins = int(entry.duration // 60)
    secs = int(entry.duration % 60)

    segments = []
    for seg in entry.segments:
        start = seg.get("start", 0)
        m = int(start // 60)
        s = int(start % 60)
        seg_dict = {
            "start": start,
            "end": seg.get("end", 0),
            "timestamp": f"{m}:{s:02d}",
            "text": seg.get("text", "").strip(),
        }
        if entry.source_url:
            yt_link = _youtube_timestamp_link(entry.source_url, start)
            if yt_link:
                seg_dict["youtube_link"] = yt_link
        segments.append(seg_dict)

    return JSONResponse(
        {
            "title": entry.title,
            "duration": entry.duration,
            "duration_formatted": f"{mins}:{secs:02d}",
            "language": entry.language,
            "model_size": entry.model_size,
            "date": date_str,
            "source_url": entry.source_url,
            "file_path": entry.file_path,
            "text": entry.text,
            "segments": segments,
        }
    )


@app.get("/api/memory/search")
async def api_memory_search(
    q: str = Query(""),  # noqa: B008
    limit: int = Query(50),  # noqa: B008
):
    """Keyword search across all stored transcriptions."""
    if not q or len(q) < 2:
        return JSONResponse({"results": [], "match_count": 0})

    memory = get_transcription_memory()
    entries = memory.get_all_with_segments()
    query_lower = q.lower()
    results = []

    # Build file_path -> cache_key lookup once
    cache_key_map = {
        e["file_path"]: e["cache_key"] for e in memory.list_all() if e.get("file_path")
    }

    for entry in entries:
        segs = entry.get("segments", [])
        for seg in segs:
            text = seg.get("text", "")
            if query_lower in text.lower():
                start = seg.get("start", 0)
                m = int(start // 60)
                s = int(start % 60)

                results.append(
                    {
                        "title": entry.get("title", ""),
                        "cache_key": cache_key_map.get(entry.get("file_path", ""), ""),
                        "start": start,
                        "timestamp": f"{m}:{s:02d}",
                        "text": text.strip(),
                        "source_url": entry.get("source_url", ""),
                    }
                )
                if len(results) >= limit:
                    break
        if len(results) >= limit:
            break

    return JSONResponse(
        {
            "results": results,
            "match_count": len(results),
            "query": q,
        }
    )


@app.delete("/api/memory/{cache_key:path}")
async def api_memory_delete(cache_key: str):
    """Delete a single transcription from memory."""
    memory = get_transcription_memory()
    deleted = memory.delete_by_cache_key(cache_key)
    if not deleted:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse({"ok": True})


@app.post("/api/memory/reveal/{cache_key:path}")
async def api_memory_reveal(cache_key: str, target: str = Query("audio")):
    """Reveal file in Finder (macOS) or file manager."""
    import platform

    memory = get_transcription_memory()
    entry = memory.get_by_cache_key(cache_key)
    if not entry or not entry.file_path:
        return JSONResponse({"error": "No file path stored"}, status_code=404)

    if target == "transcript":
        # Reveal the markdown transcript file
        import sqlite3 as _sq

        md_path = ""
        try:
            with _sq.connect(memory.db_path) as _c:
                _r = _c.execute(
                    "SELECT md_path FROM transcriptions WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
                if _r:
                    md_path = _r[0] or ""
        except Exception:
            pass
        if not md_path or not os.path.exists(md_path):
            return JSONResponse({"error": "No transcript file found"}, status_code=404)
        file_path = md_path
    else:
        # Default: reveal the audio file
        file_path = os.path.realpath(os.path.expanduser(entry.file_path))

        if not os.path.exists(file_path):
            # Try the markdown file instead
            import sqlite3 as _sq

            _md = ""
            try:
                with _sq.connect(memory.db_path) as _c:
                    _r = _c.execute(
                        "SELECT md_path FROM transcriptions WHERE cache_key = ?",
                        (cache_key,),
                    ).fetchone()
                    if _r:
                        _md = _r[0] or ""
            except Exception:
                pass
            if _md and os.path.exists(_md):
                file_path = _md
            else:
                # File deleted/moved — try to open its parent directory instead
                parent = os.path.dirname(file_path)
                if os.path.isdir(parent):
                    try:
                        if platform.system() == "Darwin":
                            subprocess.Popen(["open", parent])
                        elif platform.system() == "Linux":
                            subprocess.Popen(["xdg-open", parent])
                        else:
                            subprocess.Popen(["explorer", parent])
                    except Exception:
                        pass
                    return JSONResponse(
                        {
                            "error": f"File no longer exists — opened folder instead: {parent}"
                        },
                        status_code=404,
                    )
                return JSONResponse(
                    {"error": f"File no longer exists: {file_path}"}, status_code=404
                )

    try:
        if platform.system() == "Darwin":
            # AppleScript is more reliable than open -R for special characters
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    f'tell application "Finder" to reveal POSIX file "{file_path}"',
                    "-e",
                    'tell application "Finder" to activate',
                ]
            )
        elif platform.system() == "Linux":
            subprocess.Popen(["xdg-open", os.path.dirname(file_path)])
        else:
            subprocess.Popen(["explorer", "/select,", file_path])
    except Exception:
        return JSONResponse({"error": "Could not open file manager"}, status_code=500)

    return JSONResponse({"ok": True, "file_path": file_path})


@app.get("/api/memory/share/{cache_key:path}")
async def api_memory_share(cache_key: str):
    """Generate and download a self-contained HTML page for a transcript."""
    memory = get_transcription_memory()
    entry = memory.get_by_cache_key(cache_key)
    if not entry:
        return JSONResponse({"error": "Not found"}, status_code=404)

    html_content = _generate_share_html(entry)
    safe_title = re.sub(r"[^\w\s\-]", "", entry.title or "transcript")
    safe_title = re.sub(r"\s+", "_", safe_title).strip("_")[:60] or "transcript"

    return Response(
        content=html_content,
        media_type="text/html",
        headers={"Content-Disposition": f"attachment; filename={safe_title}.html"},
    )


def _generate_share_html(entry) -> str:
    """Generate a self-contained HTML page for a transcript."""
    from datetime import datetime

    title = html_mod.escape(entry.title or "Untitled")
    language = html_mod.escape(entry.language or "")
    model = html_mod.escape(entry.model_size or "")
    mins = int(entry.duration // 60)
    secs = int(entry.duration % 60)
    duration_fmt = f"{mins}:{secs:02d}"
    date_str = (
        datetime.fromtimestamp(entry.created_at).strftime("%Y-%m-%d %H:%M")
        if entry.created_at
        else ""
    )
    source_url = entry.source_url or ""

    source_html = ""
    if source_url:
        escaped_url = html_mod.escape(source_url)
        source_html = f' &middot; <a href="{escaped_url}" style="color:#00F060;">{escaped_url[:80]}</a>'

    segments_html = ""
    for seg in entry.segments:
        start = seg.get("start", 0)
        m = int(start // 60)
        s = int(start % 60)
        ts = f"{m}:{s:02d}"
        text = html_mod.escape(seg.get("text", "").strip())

        yt_link = _youtube_timestamp_link(source_url, start) if source_url else ""
        if yt_link:
            ts_html = f'<a href="{html_mod.escape(yt_link)}" style="color:#00F060;text-decoration:none;">{ts}</a>'
        else:
            ts_html = ts

        segments_html += f"""<div style="display:flex;gap:16px;padding:8px 0;border-bottom:1px solid rgba(0,240,96,0.1);">
<div style="font-family:Monaco,Menlo,monospace;font-size:12px;color:rgba(0,240,96,0.6);min-width:50px;">{ts_html}</div>
<div style="font-size:14px;line-height:1.7;color:#00F060;">{text}</div>
</div>"""

    if not segments_html and entry.text:
        segments_html = f'<div style="padding:16px 0;font-size:14px;line-height:1.8;color:#00F060;">{html_mod.escape(entry.text)}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Augent</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#000;color:#00F060;font-family:'Montserrat',sans-serif;padding:40px 24px;max-width:900px;margin:0 auto;}}
::selection{{background:#00F060;color:#000}}
a{{color:#00F060}}
h1{{font-size:24px;font-weight:700;margin-bottom:12px;letter-spacing:-0.3px}}
.meta{{font-size:12px;color:rgba(0,240,96,0.6);margin-bottom:24px}}
.divider{{border:none;border-top:1px solid rgba(0,240,96,0.15);margin:24px 0}}
.footer{{font-size:11px;color:rgba(0,240,96,0.4);margin-top:40px;text-align:center}}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">{duration_fmt} &middot; {language} &middot; {model} &middot; {date_str}{source_html}</div>
<hr class="divider">
{segments_html}
<hr class="divider">
<div class="footer">Generated by Augent &middot; {date_str}</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------


def _kill_port(port: int):
    """Kill any process using the specified port (excluding ourselves)."""
    import signal

    my_pid = os.getpid()
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True
        )
        pids = result.stdout.strip().split("\n")
        for pid in pids:
            if pid and int(pid) != my_pid:
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

    os.write(
        1,
        f"\n  WebUI is live at \033]8;;http://localhost:{args.port}\033\\http://localhost:{args.port}\033]8;;\033\\\n  Press Ctrl+C to stop.\n\n".encode(),
    )

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
