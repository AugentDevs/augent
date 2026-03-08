"""
Augent Speakers - Speaker diarization

Uses pyannote-audio for state-of-the-art speaker diarization.
Automatically detects who speaks when and how many speakers are present.

Requires:
    pip install augent[speakers]
    A Hugging Face token (free) to download the pretrained model.
    Accept the license at https://huggingface.co/pyannote/speaker-diarization-3.1
    Then set HF_TOKEN env var or run: huggingface-cli login
"""

import os
from typing import Any, Dict, List, Optional

from .core import transcribe_audio
from .memory import get_transcription_memory


def _get_hf_token() -> Optional[str]:
    """Get Hugging Face token from environment or cached login."""
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token:
        return token

    # Check huggingface-cli login token
    for token_path in [
        os.path.expanduser("~/.huggingface/token"),
        os.path.expanduser("~/.cache/huggingface/token"),
    ]:
        if os.path.exists(token_path):
            with open(token_path) as f:
                stored = f.read().strip()
                if stored:
                    return stored

    return None


def identify_speakers(
    audio_path: str,
    model_size: str = "tiny",
    num_speakers: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Identify speakers in audio and return speaker-labeled transcript.

    Runs faster-whisper transcription (from memory) then pyannote diarization,
    merging results by timestamp overlap.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Step 1: Get transcription (from memory)
    transcription = transcribe_audio(audio_path, model_size)

    # Step 2: Check diarization memory
    memory = get_transcription_memory()
    audio_hash = memory.hash_audio_file(audio_path)
    stored_diarization = memory.get_diarization(audio_hash, num_speakers)

    if stored_diarization:
        turns = stored_diarization["turns"]
        speakers = stored_diarization["speakers"]
    else:
        # Step 3: Run diarization with pyannote
        try:
            from pyannote.audio import Pipeline
        except ImportError:
            raise ImportError(
                "pyannote-audio is not installed. Install with: pip install augent[speakers]\n"
                "Or directly: pip install pyannote-audio"
            ) from None

        hf_token = _get_hf_token()
        if not hf_token:
            raise RuntimeError(
                "Hugging Face token required for pyannote speaker diarization.\n"
                "1. Create a free token at https://huggingface.co/settings/tokens\n"
                "2. Accept the model license at https://huggingface.co/pyannote/speaker-diarization-3.1\n"
                "3. Set the token: export HF_TOKEN=your_token\n"
                "   Or run: huggingface-cli login"
            )

        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )

        # Run diarization
        kwargs = {}
        if num_speakers is not None:
            kwargs["num_speakers"] = num_speakers

        diarization = pipeline(audio_path, **kwargs)

        # Extract turns from pyannote Annotation
        turns = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            turns.append(
                {
                    "speaker": speaker,
                    "start": float(turn.start),
                    "end": float(turn.end),
                }
            )

        speakers = sorted({t["speaker"] for t in turns})

        # Store the result
        memory.set_diarization(audio_hash, speakers, turns, num_speakers)

    # Step 4: Merge transcription segments with speaker turns
    merged = _merge(transcription["segments"], turns)

    return {
        "speakers": speakers,
        "segments": merged,
        "duration": transcription["duration"],
        "duration_formatted": f"{int(transcription['duration'] // 60)}:{int(transcription['duration'] % 60):02d}",
        "language": transcription["language"],
        "cached": transcription.get("cached", False),
    }


def _merge(transcript_segments: List[Dict], speaker_turns: List[Dict]) -> List[Dict]:
    """Merge transcription segments with speaker turns by timestamp overlap."""
    merged = []
    for seg in transcript_segments:
        seg_start = seg["start"]
        seg_end = seg["end"]

        # Find speaker with maximum overlap
        best_speaker = "Unknown"
        best_overlap = 0.0

        for turn in speaker_turns:
            overlap_start = max(seg_start, turn["start"])
            overlap_end = min(seg_end, turn["end"])
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn["speaker"]

        merged.append(
            {
                "speaker": best_speaker,
                "start": seg_start,
                "end": seg_end,
                "text": seg["text"].strip(),
                "timestamp": f"{int(seg_start // 60)}:{int(seg_start % 60):02d}",
            }
        )

    return merged
