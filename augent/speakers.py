"""
Augent Speakers - Speaker diarization

Uses simple_diarizer (built on speechbrain) to identify who speaks when.
No auth tokens required — all models are open.
"""

import os
from typing import Any, Dict, List, Optional

from .core import transcribe_audio
from .memory import get_transcription_memory


def identify_speakers(
    audio_path: str,
    model_size: str = "tiny",
    num_speakers: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Identify speakers in audio and return speaker-labeled transcript.

    Runs faster-whisper transcription (from memory) then speechbrain diarization,
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
        # Step 3: Run diarization
        from simple_diarizer.diarizer import Diarizer

        diar = Diarizer(embed_model="ecapa", cluster_method="sc")
        raw_segments = diar.diarize(audio_path, num_speakers=num_speakers)

        # Extract turns
        turns = []
        for seg in raw_segments:
            turns.append(
                {
                    "speaker": seg["label"],
                    "start": float(seg["start"]),
                    "end": float(seg["end"]),
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
