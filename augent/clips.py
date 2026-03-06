"""
Augent Clips - Extract audio segments around keyword matches

Provides functionality to:
- Extract clips around keyword timestamps
- Add configurable padding before/after
- Export to various audio formats
- Batch export multiple clips
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Generator, List, Optional


@dataclass
class ClipInfo:
    """Information about an exported clip."""

    output_path: str
    keyword: str
    timestamp: str
    start_seconds: float
    end_seconds: float
    duration: float


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available."""
    return shutil.which("ffmpeg") is not None


def extract_clip_ffmpeg(
    audio_path: str,
    output_path: str,
    start_seconds: float,
    end_seconds: float,
    format: str = "mp3",
) -> bool:
    """
    Extract an audio clip using ffmpeg.

    Args:
        audio_path: Path to source audio file
        output_path: Path for output clip
        start_seconds: Start time in seconds
        end_seconds: End time in seconds
        format: Output format (mp3, wav, m4a, etc.)

    Returns:
        True if successful, False otherwise
    """
    duration = end_seconds - start_seconds

    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-i",
        audio_path,
        "-ss",
        str(start_seconds),
        "-t",
        str(duration),
        "-acodec",
        "libmp3lame" if format == "mp3" else "copy",
        "-q:a",
        "2",  # Quality setting for mp3
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result.returncode == 0
    except Exception:
        return False


def extract_clip_pydub(
    audio_path: str,
    output_path: str,
    start_seconds: float,
    end_seconds: float,
    format: str = "mp3",
) -> bool:
    """
    Extract an audio clip using pydub (fallback if ffmpeg not available directly).

    Args:
        audio_path: Path to source audio file
        output_path: Path for output clip
        start_seconds: Start time in seconds
        end_seconds: End time in seconds
        format: Output format

    Returns:
        True if successful, False otherwise
    """
    try:
        from pydub import AudioSegment

        # Load audio
        audio = AudioSegment.from_file(audio_path)

        # Convert to milliseconds
        start_ms = int(start_seconds * 1000)
        end_ms = int(end_seconds * 1000)

        # Extract clip
        clip = audio[start_ms:end_ms]

        # Export
        clip.export(output_path, format=format)
        return True

    except Exception:
        return False


def format_filename(
    keyword: str, timestamp_seconds: float, index: int, format: str = "mp3"
) -> str:
    """
    Generate a clean filename for a clip.

    Args:
        keyword: The keyword found
        timestamp_seconds: Timestamp in seconds
        index: Match index number
        format: File format/extension

    Returns:
        Formatted filename
    """
    # Clean keyword for filename
    clean_keyword = (
        "".join(c if c.isalnum() or c in "-_ " else "_" for c in keyword)
        .strip()
        .replace(" ", "_")[:30]
    )

    # Format timestamp
    mins = int(timestamp_seconds // 60)
    secs = int(timestamp_seconds % 60)
    ts = f"{mins:02d}m{secs:02d}s"

    return f"match_{index:03d}_{clean_keyword}_{ts}.{format}"


class ClipExtractor:
    """Extract audio clips around keyword matches."""

    def __init__(
        self,
        padding_before: float = 5.0,
        padding_after: float = 5.0,
        output_format: str = "mp3",
        use_pydub: bool = False,
    ):
        """
        Initialize the clip extractor.

        Args:
            padding_before: Seconds of audio before the keyword
            padding_after: Seconds of audio after the keyword
            output_format: Output audio format (mp3, wav, m4a)
            use_pydub: Force use of pydub instead of ffmpeg
        """
        self.padding_before = padding_before
        self.padding_after = padding_after
        self.output_format = output_format
        self.use_pydub = use_pydub

        # Check ffmpeg availability
        self.has_ffmpeg = check_ffmpeg()
        if not self.has_ffmpeg and not use_pydub:
            try:
                import pydub

                self.use_pydub = True
            except ImportError as err:
                raise RuntimeError(
                    "Neither ffmpeg nor pydub is available. "
                    "Install ffmpeg or run: pip install pydub"
                ) from err

    def extract_clip(
        self,
        audio_path: str,
        output_path: str,
        timestamp_seconds: float,
        duration: Optional[float] = None,
    ) -> bool:
        """
        Extract a single clip around a timestamp.

        Args:
            audio_path: Source audio file
            output_path: Output clip path
            timestamp_seconds: Center timestamp for the clip
            duration: Optional override for total duration

        Returns:
            True if successful
        """
        # Calculate start and end
        start = max(0, timestamp_seconds - self.padding_before)
        if duration:
            end = timestamp_seconds + duration
        else:
            end = timestamp_seconds + self.padding_after

        # Extract
        if self.use_pydub or not self.has_ffmpeg:
            return extract_clip_pydub(
                audio_path, output_path, start, end, self.output_format
            )
        else:
            return extract_clip_ffmpeg(
                audio_path, output_path, start, end, self.output_format
            )

    def extract_matches(
        self,
        audio_path: str,
        matches: List[Dict],
        output_dir: str,
        on_progress: Optional[Callable] = None,
    ) -> Generator[ClipInfo, None, None]:
        """
        Extract clips for all keyword matches.

        Args:
            audio_path: Source audio file
            matches: List of match dicts with timestamp_seconds, keyword
            output_dir: Directory to save clips
            on_progress: Optional callback(index, total, clip_info)

        Yields:
            ClipInfo for each successfully extracted clip
        """
        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        total = len(matches)

        for i, match in enumerate(matches):
            keyword = match.get("keyword", "unknown")
            timestamp_seconds = match.get("timestamp_seconds", 0)

            # Generate filename
            filename = format_filename(
                keyword, timestamp_seconds, i + 1, self.output_format
            )
            clip_path = str(output_path / filename)

            # Calculate times
            start = max(0, timestamp_seconds - self.padding_before)
            end = timestamp_seconds + self.padding_after

            # Extract
            success = self.extract_clip(audio_path, clip_path, timestamp_seconds)

            if success:
                info = ClipInfo(
                    output_path=clip_path,
                    keyword=keyword,
                    timestamp=match.get("timestamp", ""),
                    start_seconds=start,
                    end_seconds=end,
                    duration=end - start,
                )

                if on_progress:
                    on_progress(i + 1, total, info)

                yield info

    def extract_all(
        self,
        audio_path: str,
        matches: List[Dict],
        output_dir: str,
        on_progress: Optional[Callable] = None,
    ) -> List[ClipInfo]:
        """
        Extract all clips and return as a list.

        Args:
            audio_path: Source audio file
            matches: List of match dicts
            output_dir: Directory to save clips
            on_progress: Optional progress callback

        Returns:
            List of ClipInfo for successfully extracted clips
        """
        return list(self.extract_matches(audio_path, matches, output_dir, on_progress))


def export_clips(
    audio_path: str,
    matches: List[Dict],
    output_dir: str,
    padding: float = 5.0,
    format: str = "mp3",
    on_progress: Optional[Callable] = None,
) -> List[Dict]:
    """
    Convenience function to export clips for all matches.

    Args:
        audio_path: Source audio file
        matches: List of match dicts with timestamp_seconds, keyword
        output_dir: Directory to save clips
        padding: Seconds of audio before and after each match
        format: Output audio format
        on_progress: Optional callback(index, total, clip_info)

    Returns:
        List of dicts with clip information
    """
    extractor = ClipExtractor(
        padding_before=padding, padding_after=padding, output_format=format
    )

    clips = extractor.extract_all(audio_path, matches, output_dir, on_progress)

    return [
        {
            "output_path": c.output_path,
            "keyword": c.keyword,
            "timestamp": c.timestamp,
            "start_seconds": c.start_seconds,
            "end_seconds": c.end_seconds,
            "duration": c.duration,
        }
        for c in clips
    ]


def merge_clips(
    clip_paths: List[str], output_path: str, gap_seconds: float = 0.5
) -> bool:
    """
    Merge multiple clips into a single compilation.

    Args:
        clip_paths: List of clip file paths to merge
        output_path: Output file path
        gap_seconds: Silence gap between clips

    Returns:
        True if successful
    """
    if not check_ffmpeg():
        raise RuntimeError("ffmpeg is required for merging clips")

    if not clip_paths:
        return False

    # Create a file list for ffmpeg concat
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for path in clip_paths:
            f.write(f"file '{path}'\n")
        list_file = f.name

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_file,
            "-acodec",
            "libmp3lame",
            "-q:a",
            "2",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=300)
        return result.returncode == 0

    finally:
        os.unlink(list_file)
