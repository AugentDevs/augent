"""
Augent Core - Local audio keyword search using faster-whisper

Transcribes audio files locally using faster-whisper (optimized Whisper)
and searches for keywords with timestamps.

Features:
- Transcription memory (avoid re-processing same files)
- Model caching (keep models loaded in memory)
- Streaming transcription with progress callbacks
- Proximity search
"""

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from .memory import get_model_cache, get_transcription_memory
from .search import find_keyword_matches, search_with_proximity


@dataclass
class TranscriptionProgress:
    """Progress update during transcription."""

    status: str
    progress: float
    message: str
    segment: Optional[Dict] = None


def transcribe_audio(
    audio_path: str,
    model_size: str = "tiny",
    use_cache: bool = True,
    device: str = "auto",
    compute_type: str = "auto",
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Transcribe an audio file using faster-whisper.

    Args:
        audio_path: Path to the audio file (MP3, WAV, etc.)
        model_size: Whisper model size - "tiny", "base", "small", "medium", "large"
        use_cache: Use cached transcription if available
        device: Device to use (auto, cpu, cuda)
        compute_type: Compute type (auto, float16, int8)
        language: Force specific language (None for auto-detect)

    Returns:
        dict with keys: text, language, duration, segments, words
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if use_cache:
        memory = get_transcription_memory()
        stored = memory.get(audio_path, model_size)
        if stored:
            return {
                "text": stored.text,
                "language": stored.language,
                "duration": stored.duration,
                "segments": stored.segments,
                "words": stored.words,
                "cached": True,
            }

    model_cache = get_model_cache()
    model = model_cache.get(model_size, device, compute_type)

    transcribe_options = {"word_timestamps": True, "vad_filter": True}
    if language:
        transcribe_options["language"] = language

    segments_gen, info = model.transcribe(audio_path, **transcribe_options)

    segments = []
    words = []

    for segment in segments_gen:
        seg_dict = {"start": segment.start, "end": segment.end, "text": segment.text}
        segments.append(seg_dict)

        if segment.words:
            for word in segment.words:
                words.append(
                    {"word": word.word.strip(), "start": word.start, "end": word.end}
                )

    result = {
        "text": " ".join(s["text"].strip() for s in segments),
        "language": info.language,
        "duration": info.duration,
        "segments": segments,
        "words": words,
        "cached": False,
    }

    if use_cache:
        memory = get_transcription_memory()
        memory.set(audio_path, model_size, result)

    return result


def transcribe_audio_streaming(
    audio_path: str,
    model_size: str = "tiny",
    use_cache: bool = True,
    device: str = "auto",
    compute_type: str = "auto",
    language: Optional[str] = None,
    on_progress: Optional[Callable[[TranscriptionProgress], None]] = None,
) -> Generator[TranscriptionProgress, None, Dict[str, Any]]:
    """Transcribe audio with streaming progress updates."""
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if use_cache:
        memory = get_transcription_memory()
        stored = memory.get(audio_path, model_size)
        if stored:
            progress = TranscriptionProgress(
                status="complete", progress=1.0, message="Loaded from memory"
            )
            if on_progress:
                on_progress(progress)
            yield progress

            return {
                "text": stored.text,
                "language": stored.language,
                "duration": stored.duration,
                "segments": stored.segments,
                "words": stored.words,
                "cached": True,
            }

    progress = TranscriptionProgress(
        status="loading_model", progress=0.0, message=f"Loading {model_size} model..."
    )
    if on_progress:
        on_progress(progress)
    yield progress

    model_cache = get_model_cache()
    model = model_cache.get(model_size, device, compute_type)

    progress = TranscriptionProgress(
        status="transcribing", progress=0.05, message="Starting transcription..."
    )
    if on_progress:
        on_progress(progress)
    yield progress

    transcribe_options = {"word_timestamps": True, "vad_filter": True}
    if language:
        transcribe_options["language"] = language

    segments_gen, info = model.transcribe(audio_path, **transcribe_options)

    segments = []
    words = []
    duration = info.duration if info.duration else 1.0

    for segment in segments_gen:
        seg_dict = {"start": segment.start, "end": segment.end, "text": segment.text}
        segments.append(seg_dict)

        if segment.words:
            for word in segment.words:
                words.append(
                    {"word": word.word.strip(), "start": word.start, "end": word.end}
                )

        progress_pct = min(0.95, segment.end / duration)

        progress = TranscriptionProgress(
            status="segment",
            progress=progress_pct,
            message=f"[{_format_timestamp(segment.start)}] {segment.text.strip()}",
            segment=seg_dict,
        )
        if on_progress:
            on_progress(progress)
        yield progress

    result = {
        "text": " ".join(s["text"].strip() for s in segments),
        "language": info.language,
        "duration": info.duration,
        "segments": segments,
        "words": words,
        "cached": False,
    }

    if use_cache:
        memory = get_transcription_memory()
        memory.set(audio_path, model_size, result)

    progress = TranscriptionProgress(
        status="complete",
        progress=1.0,
        message=f"Complete. Duration: {_format_timestamp(info.duration)}",
    )
    if on_progress:
        on_progress(progress)
    yield progress

    return result


def _format_timestamp(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def search_audio(
    audio_path: str,
    keywords: List[str],
    model_size: str = "tiny",
    use_cache: bool = True,
) -> Dict[str, List[Dict]]:
    """
    Main function: transcribe audio and search for keywords.

    Args:
        audio_path: Path to audio file
        keywords: List of keywords to search for
        model_size: Whisper model size
        use_cache: Use cached transcription

    Returns:
        dict grouped by keyword with matches
    """
    transcription = transcribe_audio(audio_path, model_size, use_cache=use_cache)

    matches = find_keyword_matches(transcription["words"], keywords)

    grouped: Dict[str, List[Dict]] = {}
    for match in matches:
        kw = match["keyword"]
        if kw not in grouped:
            grouped[kw] = []
        grouped[kw].append(
            {
                "timestamp": match["timestamp"],
                "timestamp_seconds": match["timestamp_seconds"],
                "snippet": match["snippet"],
            }
        )

    return grouped


def search_audio_full(
    audio_path: str,
    keywords: List[str],
    model_size: str = "tiny",
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Full output including transcription metadata."""
    transcription = transcribe_audio(audio_path, model_size, use_cache=use_cache)

    matches = find_keyword_matches(transcription["words"], keywords)

    return {
        "text": transcription["text"],
        "language": transcription["language"],
        "duration": transcription["duration"],
        "cached": transcription.get("cached", False),
        "matches": matches,
    }


def search_audio_streaming(
    audio_path: str,
    keywords: List[str],
    model_size: str = "tiny",
    use_cache: bool = True,
) -> Generator[Tuple[TranscriptionProgress, List[Dict]], None, Dict[str, Any]]:
    """Search audio with streaming progress."""
    all_matches = []

    for progress in transcribe_audio_streaming(
        audio_path, model_size, use_cache=use_cache
    ):
        yield (progress, all_matches)
        if progress.status == "complete":
            break

    transcription = transcribe_audio(audio_path, model_size, use_cache=True)
    all_matches = find_keyword_matches(transcription["words"], keywords)

    grouped: Dict[str, List[Dict]] = {}
    for match in all_matches:
        kw = match["keyword"]
        if kw not in grouped:
            grouped[kw] = []
        grouped[kw].append(
            {
                "timestamp": match["timestamp"],
                "timestamp_seconds": match["timestamp_seconds"],
                "snippet": match["snippet"],
            }
        )

    return {
        "text": transcription["text"],
        "language": transcription["language"],
        "duration": transcription["duration"],
        "matches": grouped,
        "total_matches": len(all_matches),
    }


def search_audio_proximity(
    audio_path: str,
    keyword1: str,
    keyword2: str,
    max_distance: int = 30,
    model_size: str = "tiny",
    use_cache: bool = True,
) -> List[Dict]:
    """Find where keyword1 appears near keyword2."""
    transcription = transcribe_audio(audio_path, model_size, use_cache=use_cache)

    return search_with_proximity(
        transcription["words"], keyword1, keyword2, max_distance
    )


def get_memory_stats() -> Dict[str, Any]:
    """Get transcription memory statistics."""
    memory = get_transcription_memory()
    return memory.stats()


def clear_memory() -> int:
    """Clear transcription memory. Returns number of entries cleared."""
    memory = get_transcription_memory()
    return memory.clear()


def list_memories() -> list:
    """List all stored transcriptions with metadata."""
    memory = get_transcription_memory()
    return memory.list_all()


def get_memory_by_title(title: str) -> list:
    """Look up stored transcriptions by title."""
    memory = get_transcription_memory()
    return memory.get_by_title(title)


def clear_model_cache() -> None:
    """Clear loaded models from memory."""
    model_cache = get_model_cache()
    model_cache.clear()
