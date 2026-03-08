"""
Augent - Local audio keyword search using faster-whisper

Extract timestamped keyword matches from audio files with:
- Transcription memory (skip re-processing)
- Proximity search (find keywords near each other)
- Multiple export formats (JSON, CSV, SRT, VTT, Markdown)
- Audio clip extraction

Usage:
    from augent import search_audio, transcribe_audio

    # Basic keyword search
    results = search_audio("podcast.mp3", ["lucrative", "funding"])

    # Full transcription
    transcription = transcribe_audio("podcast.mp3")

CLI:
    augent search audio.mp3 "keyword1,keyword2"
    augent transcribe audio.mp3 --format srt

Web UI:
    augent-web

MCP Server (for Claude):
    python -m augent.mcp
"""

from .cli import main
from .clips import (
    ClipExtractor,
    export_clips,
)
from .core import (
    TranscriptionProgress,
    clear_memory,
    clear_model_cache,
    get_memory_by_title,
    get_memory_stats,
    list_memories,
    search_audio,
    search_audio_full,
    search_audio_proximity,
    search_audio_streaming,
    transcribe_audio,
    transcribe_audio_streaming,
)
from .export import (
    Exporter,
    export_matches,
    export_transcription,
)
from .memory import (
    MemorizedTranscription,
    ModelCache,
    TranscriptionMemory,
    get_model_cache,
    get_transcription_memory,
)
from .search import (
    KeywordSearcher,
    find_keyword_matches,
    search_with_proximity,
)

# Optional: Speaker diarization (requires pyannote-audio)
try:
    from .speakers import identify_speakers
except ImportError:
    identify_speakers = None

# Optional: Semantic search + chapters (requires sentence-transformers)
try:
    from .embeddings import deep_search, detect_chapters, search_memory
except ImportError:
    deep_search = None
    detect_chapters = None
    search_memory = None

# Optional: Text-to-speech (requires kokoro)
try:
    from .tts import read_aloud, text_to_speech
except ImportError:
    text_to_speech = None
    read_aloud = None

# Optional: Audio source separation (requires demucs)
try:
    from .separator import get_vocal_stem
    from .separator import separate_audio as separate_audio_stems
except ImportError:
    separate_audio_stems = None
    get_vocal_stem = None

__version__ = "2026.3.8"
__all__ = [
    # Core functions
    "search_audio",
    "search_audio_full",
    "transcribe_audio",
    "transcribe_audio_streaming",
    "search_audio_proximity",
    "search_audio_streaming",
    # Memory management
    "get_memory_stats",
    "clear_memory",
    "clear_model_cache",
    "list_memories",
    "get_memory_by_title",
    "get_transcription_memory",
    "get_model_cache",
    # Search
    "find_keyword_matches",
    "search_with_proximity",
    "KeywordSearcher",
    # Export
    "export_matches",
    "export_transcription",
    "export_clips",
    "Exporter",
    "ClipExtractor",
    # Classes
    "TranscriptionProgress",
    "TranscriptionMemory",
    "MemorizedTranscription",
    "ModelCache",
    # Optional: Speakers
    "identify_speakers",
    # Optional: Semantic search + chapters
    "deep_search",
    "detect_chapters",
    "search_memory",
    # Optional: Text-to-speech
    "text_to_speech",
    "read_aloud",
    # Optional: Audio source separation
    "separate_audio_stems",
    "get_vocal_stem",
    # CLI
    "main",
    # Version
    "__version__",
]
