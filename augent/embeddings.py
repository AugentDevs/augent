"""
Augent Embeddings - Semantic search and chapter detection

Uses sentence-transformers for embedding-based audio analysis:
- deep_search: Find content by meaning, not just keywords
- detect_chapters: Auto-detect topic boundaries in audio
"""

import csv
import io
import os
import threading
from typing import Any, Dict, List, Optional

import numpy as np

from .core import transcribe_audio
from .memory import get_transcription_memory

EMBEDDING_MODEL = "all-MiniLM-L6-v2"


class EmbeddingModelCache:
    """In-memory cache for loaded sentence-transformer models."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._models = {}
                    cls._instance._model_lock = threading.Lock()
        return cls._instance

    def get(self, model_name: str = EMBEDDING_MODEL):
        """Get a cached model or load a new one."""
        with self._model_lock:
            if model_name not in self._models:
                from sentence_transformers import SentenceTransformer

                self._models[model_name] = SentenceTransformer(model_name)
            return self._models[model_name]

    def clear(self):
        """Clear all cached models."""
        with self._model_lock:
            self._models.clear()


def _get_embedding_model_cache() -> EmbeddingModelCache:
    return EmbeddingModelCache()


def _cosine_similarity(query: np.ndarray, embeddings: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between a query vector and a matrix of embeddings."""
    dot = np.dot(embeddings, query.T).flatten()
    norm_q = np.linalg.norm(query)
    norm_e = np.linalg.norm(embeddings, axis=1)
    return dot / (norm_q * norm_e + 1e-8)


def _highlight_keywords(text: str, keywords: List[str]) -> str:
    """Wrap keyword occurrences in **bold** markers for terminal display."""
    import re

    for kw in keywords:
        if not kw or not kw.strip():
            continue
        pattern = re.compile(r"(" + re.escape(kw) + r")", re.IGNORECASE)
        text = pattern.sub(r"**\1**", text)
    return text


def _build_snippet(
    segments: list,
    center_idx: int,
    target_words: int = 25,
    highlight: Optional[List[str]] = None,
) -> str:
    """Build a ~target_words snippet by expanding from center segment into neighbors."""
    words = segments[center_idx].get("text", "").strip().split()

    left = center_idx - 1
    right = center_idx + 1

    while len(words) < target_words:
        added = False
        if right < len(segments):
            words.extend(segments[right].get("text", "").strip().split())
            right += 1
            added = True
        if len(words) < target_words and left >= 0:
            words = segments[left].get("text", "").strip().split() + words
            left -= 1
            added = True
        if not added:
            break

    trimmed = len(words) > target_words
    if trimmed:
        words = words[:target_words]

    text = " ".join(words)

    # Highlight keywords before adding ellipsis
    if highlight:
        text = _highlight_keywords(text, highlight)

    # Ellipsis: content exists before/after our snippet
    if (left + 1) > 0:
        text = "..." + text
    if right < len(segments) or trimmed:
        text = text + "..."

    return text


def _ranked_semantic_search(
    query_embedding: np.ndarray,
    segment_embeddings: np.ndarray,
    segments_meta: List[dict],
    query: str,
    top_k: int,
    context_words: int = 25,
    dedup_seconds: float = 0,
) -> List[dict]:
    """Rank segments by cosine similarity to query, with dedup and snippet building.

    Each entry in segments_meta must have: seg, seg_idx, file_segments.
    Optional keys: title, file_path (included in results when present).
    """
    similarities = _cosine_similarity(
        query_embedding.reshape(1, -1), segment_embeddings
    )

    # Overcollect candidates when dedup is on
    candidate_k = (
        min(top_k * 3, len(segments_meta))
        if dedup_seconds > 0
        else min(top_k, len(segments_meta))
    )
    top_indices = np.argsort(-similarities)[:candidate_k]

    # Highlight query words (4+ chars to skip common words)
    highlight = [w for w in query.split() if len(w) >= 4]

    results = []
    used_ranges = {}  # file_key -> [(start, end)]

    for idx in top_indices:
        if len(results) >= top_k:
            break

        meta = segments_meta[idx]
        seg = meta["seg"]
        start = seg.get("start", seg.get("start", 0))
        end = seg.get("end", 0)

        # Dedup by time range, keyed per file when multi-file
        if dedup_seconds > 0:
            file_key = meta.get("file_path", "_single")
            ranges = used_ranges.get(file_key, [])
            merged = any(
                abs(start - ur[0]) < dedup_seconds or abs(start - ur[1]) < dedup_seconds
                for ur in ranges
            )
            if merged:
                continue
            used_ranges.setdefault(file_key, []).append((start, end))

        entry = {
            "start": start,
            "end": end,
            "text": _build_snippet(
                meta["file_segments"],
                meta["seg_idx"],
                target_words=context_words,
                highlight=highlight,
            ),
            "timestamp": f"{int(start // 60)}:{int(start % 60):02d}",
            "similarity": round(float(similarities[idx]), 4),
        }

        # Include multi-file metadata when present
        if "title" in meta:
            entry["title"] = meta["title"]
        if "file_path" in meta:
            entry["file_path"] = meta["file_path"]

        results.append(entry)

    return results


def _get_or_compute_embeddings(
    segments: List[Dict], audio_hash: str, model_name: str = EMBEDDING_MODEL
) -> np.ndarray:
    """Get embeddings from memory or compute them."""
    memory = get_transcription_memory()

    # Check memory
    stored = memory.get_embeddings(audio_hash, model_name)
    if stored is not None:
        return stored["embeddings"]

    # Compute embeddings
    model = _get_embedding_model_cache().get(model_name)
    texts = [seg["text"].strip() for seg in segments]
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    # Store them
    memory.set_embeddings(
        audio_hash,
        model_name,
        embeddings,
        segment_count=len(segments),
        embedding_dim=embeddings.shape[1],
    )

    return embeddings


def _write_results_csv(results: List[Dict], output_path: str, query: str) -> str:
    """Write search results to a CSV file. Returns the absolute path written."""
    path = os.path.expanduser(output_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    # Strip **bold** markers from snippets for clean CSV
    import re

    bold_pattern = re.compile(r"\*\*(.+?)\*\*")

    buf = io.StringIO()
    writer = csv.writer(buf)

    # Detect columns from first result
    has_title = any("title" in r for r in results)
    has_similarity = any("similarity" in r for r in results)

    # Header
    header = []
    if has_title:
        header.extend(["Source", "Timestamp", "Snippet"])
    else:
        header.extend(["Timestamp", "Snippet"])
    if has_similarity:
        header.append("Similarity")
    writer.writerow(header)

    for r in results:
        text = r.get("text", "")
        text = bold_pattern.sub(r"\1", text)  # strip bold markers
        text = text.replace("...", "").strip()

        row = []
        if has_title:
            row.append(r.get("title", ""))
        row.append(r.get("timestamp", ""))
        row.append(text)
        if has_similarity:
            row.append(r.get("similarity", ""))
        writer.writerow(row)

    with open(path, "w", newline="") as f:
        f.write(buf.getvalue())

    # Strip macOS quarantine flag
    import platform
    import subprocess

    if platform.system() == "Darwin":
        try:
            subprocess.run(
                ["xattr", "-d", "com.apple.quarantine", path], capture_output=True
            )
        except Exception:
            pass

    return os.path.abspath(path)


def deep_search(
    audio_path: str,
    query: str,
    model_size: str = "tiny",
    top_k: int = 5,
    context_words: int = 25,
    dedup_seconds: float = 0,
) -> Dict[str, Any]:
    """
    Semantic search across audio transcription.

    Finds segments by meaning, not just keywords.

    Args:
        context_words: Words of context per result (default 25, use 150 for full evidence blocks).
        dedup_seconds: Merge matches from the same time range (0 = off).
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Get transcription (cached)
    transcription = transcribe_audio(audio_path, model_size)
    segments = transcription["segments"]

    if not segments:
        return {
            "query": query,
            "results": [],
            "total_segments": 0,
            "model_used": model_size,
        }

    # Get audio hash for embedding memory
    memory = get_transcription_memory()
    audio_hash = memory.hash_audio_file(audio_path)

    # Get or compute segment embeddings
    segment_embeddings = _get_or_compute_embeddings(segments, audio_hash)

    # Encode query
    model = _get_embedding_model_cache().get()
    query_embedding = model.encode(
        query, convert_to_numpy=True, show_progress_bar=False
    )

    # Build metadata list for shared ranking function
    segments_meta = [
        {"seg": seg, "seg_idx": i, "file_segments": segments}
        for i, seg in enumerate(segments)
    ]

    results = _ranked_semantic_search(
        query_embedding,
        segment_embeddings,
        segments_meta,
        query,
        top_k,
        context_words,
        dedup_seconds,
    )

    return {
        "query": query,
        "results": results,
        "total_segments": len(segments),
        "model_used": model_size,
        "cached": transcription.get("cached", False),
    }


def _search_memory_keyword(query: str, top_k: int, entries: list) -> Dict[str, Any]:
    """Keyword mode: case-insensitive substring match on segment text."""
    query_lower = query.lower()
    results = []
    total_segments = 0

    for entry in entries:
        segments = entry["segments"]
        if not segments:
            continue
        total_segments += len(segments)

        for seg_idx, seg in enumerate(segments):
            text = seg.get("text", "")
            if query_lower in text.lower():
                start = seg.get("start", 0)
                results.append(
                    {
                        "title": entry["title"],
                        "file_path": entry["file_path"],
                        "start": start,
                        "end": seg.get("end", 0),
                        "text": _build_snippet(segments, seg_idx, highlight=[query]),
                        "timestamp": f"{int(start // 60)}:{int(start % 60):02d}",
                    }
                )

    # Sort by title then timestamp for readable output
    results.sort(key=lambda r: (r["title"], r["start"]))

    # Apply top_k limit
    if top_k and len(results) > top_k:
        results = results[:top_k]

    return {
        "query": query,
        "mode": "keyword",
        "results": results,
        "match_count": len(results),
        "total_segments": total_segments,
        "files_searched": len(entries),
    }


def _search_memory_semantic(
    query: str,
    top_k: int,
    entries: list,
    context_words: int = 25,
    dedup_seconds: float = 0,
) -> Dict[str, Any]:
    """Semantic mode: embedding-based similarity search."""
    # Build global segment list and embedding matrix
    all_segments = []  # (segment_dict, title, file_path, seg_idx, file_segments)
    all_embeddings = []

    for entry in entries:
        segments = entry["segments"]
        if not segments:
            continue

        # Get or compute embeddings
        emb = entry["embeddings"]
        if emb is None or len(segments) != entry["segment_count"]:
            emb = _get_or_compute_embeddings(segments, entry["audio_hash"])

        if emb is not None and len(emb) == len(segments):
            for seg_idx, seg in enumerate(segments):
                all_segments.append(
                    {
                        "seg": seg,
                        "seg_idx": seg_idx,
                        "file_segments": segments,
                        "title": entry["title"],
                        "file_path": entry["file_path"],
                    }
                )
            all_embeddings.append(emb)

    if not all_segments:
        return {
            "query": query,
            "mode": "semantic",
            "results": [],
            "total_segments": 0,
            "files_searched": len(entries),
            "model_used": EMBEDDING_MODEL,
        }

    # Stack all embeddings into one matrix
    global_embeddings = np.vstack(all_embeddings)

    # Encode query
    model = _get_embedding_model_cache().get()
    query_embedding = model.encode(
        query, convert_to_numpy=True, show_progress_bar=False
    )

    results = _ranked_semantic_search(
        query_embedding,
        global_embeddings,
        all_segments,
        query,
        top_k,
        context_words,
        dedup_seconds,
    )

    return {
        "query": query,
        "mode": "semantic",
        "results": results,
        "total_segments": len(all_segments),
        "files_searched": len(entries),
        "model_used": EMBEDDING_MODEL,
    }


def search_memory(
    query: str,
    top_k: int = 10,
    mode: str = "keyword",
    output: Optional[str] = None,
    context_words: int = 25,
    dedup_seconds: float = 0,
) -> Dict[str, Any]:
    """
    Search across ALL stored transcriptions.

    No audio_path needed — operates entirely on what's already in memory.

    Args:
        query: Search query (keyword or natural language phrase)
        top_k: Maximum number of results to return
        mode: "keyword" (default) for literal matching,
              "semantic" for meaning-based search
        output: Optional file path to save results as CSV
        context_words: Words of context per result (default 25, use 150 for full evidence blocks).
        dedup_seconds: Merge matches from the same time range (0 = off). Semantic mode only.
    """
    if not query or not query.strip():
        raise ValueError("Missing required parameter: query")

    if mode not in ("keyword", "semantic"):
        raise ValueError(f"Invalid mode: {mode}. Must be 'keyword' or 'semantic'.")

    memory = get_transcription_memory()

    if mode == "keyword":
        entries = memory.get_all_with_segments()
        if not entries:
            result = {
                "query": query,
                "mode": "keyword",
                "results": [],
                "match_count": 0,
                "total_segments": 0,
                "files_searched": 0,
            }
        else:
            result = _search_memory_keyword(query, top_k, entries)
    else:
        entries = memory.get_all_with_embeddings(EMBEDDING_MODEL)
        if not entries:
            result = {
                "query": query,
                "mode": "semantic",
                "results": [],
                "total_segments": 0,
                "files_searched": 0,
                "model_used": EMBEDDING_MODEL,
            }
        else:
            result = _search_memory_semantic(
                query, top_k, entries, context_words, dedup_seconds
            )

    # Write CSV if output path provided
    if output and result.get("results"):
        csv_path = _write_results_csv(result["results"], output, query)
        result["csv_path"] = csv_path

    return result


def detect_chapters(
    audio_path: str,
    model_size: str = "tiny",
    sensitivity: float = 0.4,
) -> Dict[str, Any]:
    """
    Auto-detect topic chapters in audio.

    Uses rolling window cosine similarity to find topic boundaries.
    sensitivity: 0.0 = many small chapters, 1.0 = few large chapters.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Get transcription (cached)
    transcription = transcribe_audio(audio_path, model_size)
    segments = transcription["segments"]

    if len(segments) < 2:
        # Single segment = single chapter
        chapter = {
            "chapter_number": 1,
            "start": segments[0]["start"] if segments else 0,
            "end": segments[0]["end"] if segments else 0,
            "start_timestamp": "0:00",
            "end_timestamp": "0:00",
            "text": segments[0]["text"].strip() if segments else "",
            "segment_count": len(segments),
        }
        return {
            "chapters": [chapter],
            "total_chapters": 1,
            "duration": transcription["duration"],
            "model_used": model_size,
            "cached": transcription.get("cached", False),
        }

    # Get audio hash for embedding memory
    memory = get_transcription_memory()
    audio_hash = memory.hash_audio_file(audio_path)

    # Get or compute segment embeddings
    embeddings = _get_or_compute_embeddings(segments, audio_hash)

    # Compute similarity between consecutive segments
    similarities = []
    for i in range(len(embeddings) - 1):
        sim = _cosine_similarity(
            embeddings[i].reshape(1, -1), embeddings[i + 1].reshape(1, -1)
        )[0]
        similarities.append(float(sim))

    # Find boundaries where similarity drops below threshold
    boundaries = [0]
    for i, sim in enumerate(similarities):
        if sim < sensitivity:
            boundaries.append(i + 1)

    # Build chapters
    chapters = []
    for idx, start_seg_idx in enumerate(boundaries):
        end_seg_idx = (
            boundaries[idx + 1] if idx + 1 < len(boundaries) else len(segments)
        )
        chapter_segments = segments[start_seg_idx:end_seg_idx]
        chapter_text = " ".join(s["text"].strip() for s in chapter_segments)
        start = chapter_segments[0]["start"]
        end = chapter_segments[-1]["end"]
        chapters.append(
            {
                "chapter_number": idx + 1,
                "start": start,
                "end": end,
                "start_timestamp": f"{int(start // 60)}:{int(start % 60):02d}",
                "end_timestamp": f"{int(end // 60)}:{int(end % 60):02d}",
                "text": chapter_text,
                "segment_count": len(chapter_segments),
            }
        )

    return {
        "chapters": chapters,
        "total_chapters": len(chapters),
        "duration": transcription["duration"],
        "model_used": model_size,
        "cached": transcription.get("cached", False),
    }
