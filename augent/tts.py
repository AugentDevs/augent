"""
Augent TTS - Text-to-speech using Kokoro

Converts text to natural speech audio using the Kokoro 82M model.
No account, no API key — fully local, Apache 2.0 licensed.

System dependency: espeak-ng (brew install espeak-ng on macOS)
"""

import glob
import os
import re
import shutil
import subprocess
import warnings
from datetime import datetime
from typing import Any, Dict, Optional

SAMPLE_RATE = 24000

LANG_MAP = {
    "a": "American English",
    "b": "British English",
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "j": "Japanese",
    "p": "Brazilian Portuguese",
    "z": "Mandarin Chinese",
}


def text_to_speech(
    text: str,
    voice: str = "af_heart",
    output_dir: str = "~/Desktop",
    output_filename: Optional[str] = None,
    speed: float = 1.0,
) -> Dict[str, Any]:
    """
    Convert text to speech audio using Kokoro TTS.

    Args:
        text: Text to convert to speech.
        voice: Voice ID (e.g. af_heart, am_adam, bf_emma). Default: af_heart.
        output_dir: Directory to save the audio file. Default: ~/Desktop.
        output_filename: Custom filename. Auto-generated if not set.
        speed: Speech speed multiplier. Default: 1.0.

    Returns:
        Dict with file_path, voice, language, duration, sample_rate, text_length.
    """
    if not text or not text.strip():
        raise ValueError("Text cannot be empty")

    # Check espeak-ng is installed
    if not shutil.which("espeak-ng"):
        raise RuntimeError(
            "espeak-ng not found. Install with: brew install espeak-ng (macOS) "
            "or apt-get install espeak-ng (Linux)"
        )

    # Suppress all noisy warnings from torch/HF/kokoro
    import contextlib
    import io
    import logging

    for logger_name in ("kokoro", "huggingface_hub", "torch", "transformers"):
        logging.getLogger(logger_name).setLevel(logging.ERROR)
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["HF_HUB_DISABLE_WARNINGS"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    with warnings.catch_warnings(), contextlib.redirect_stderr(io.StringIO()):
        warnings.simplefilter("ignore")
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline

    # Detect language from voice prefix
    lang_code = voice[0] if voice else "a"
    language = LANG_MAP.get(lang_code, "American English")

    # Create pipeline and generate audio
    with warnings.catch_warnings(), contextlib.redirect_stderr(io.StringIO()):
        warnings.simplefilter("ignore")
        pipeline = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
        chunks = []
        for _, _, audio in pipeline(text, voice=voice, speed=speed):
            if audio is not None:
                chunks.append(audio)

    if not chunks:
        raise RuntimeError(
            "No audio generated. Check that the text and voice are valid."
        )

    # Concatenate all chunks
    full_audio = np.concatenate(chunks)

    # Prepare output path
    output_dir = os.path.expanduser(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    if not output_filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"tts_{timestamp}.mp3"

    # Ensure .mp3 extension
    if output_filename.endswith(".wav"):
        output_filename = output_filename[:-4] + ".mp3"
    elif not output_filename.endswith(".mp3"):
        output_filename += ".mp3"

    mp3_path = os.path.join(output_dir, output_filename)

    # Write temp WAV, convert to MP3 via ffmpeg, clean up
    wav_path = mp3_path.rsplit(".", 1)[0] + ".wav"
    sf.write(wav_path, full_audio, SAMPLE_RATE)

    if not shutil.which("ffmpeg"):
        # No ffmpeg — keep WAV as fallback
        duration = len(full_audio) / SAMPLE_RATE
        return {
            "file_path": wav_path,
            "voice": voice,
            "language": language,
            "duration": round(duration, 2),
            "duration_formatted": f"{int(duration // 60)}:{int(duration % 60):02d}",
            "sample_rate": SAMPLE_RATE,
            "text_length": len(text),
        }

    ffmpeg_result = subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-b:a", "192k", "-q:a", "2", mp3_path],
        capture_output=True,
    )

    duration = len(full_audio) / SAMPLE_RATE

    if ffmpeg_result.returncode != 0:
        # Conversion failed — keep the WAV so audio is not lost
        return {
            "file_path": wav_path,
            "voice": voice,
            "language": language,
            "duration": round(duration, 2),
            "duration_formatted": f"{int(duration // 60)}:{int(duration % 60):02d}",
            "sample_rate": SAMPLE_RATE,
            "text_length": len(text),
        }

    os.remove(wav_path)

    return {
        "file_path": mp3_path,
        "voice": voice,
        "language": language,
        "duration": round(duration, 2),
        "duration_formatted": f"{int(duration // 60)}:{int(duration % 60):02d}",
        "sample_rate": SAMPLE_RATE,
        "text_length": len(text),
    }


def _find_obsidian_vault() -> Optional[str]:
    """Find the first Obsidian vault on the system."""
    home = os.path.expanduser("~")
    for pattern in [
        os.path.join(home, "Desktop", "*", ".obsidian"),
        os.path.join(home, "Desktop", "*", "*", ".obsidian"),
        os.path.join(home, "Documents", "*", ".obsidian"),
        os.path.join(home, "Documents", "*", "*", ".obsidian"),
    ]:
        matches = glob.glob(pattern)
        if matches:
            return os.path.dirname(matches[0])
    return None


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting from notes for natural TTS reading."""
    lines = text.split("\n")
    cleaned = []
    skip_metadata = True

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if not skip_metadata:
                cleaned.append("")
            continue

        # Skip metadata block at top (title, source, duration, date, embeds, tips)
        if skip_metadata:
            if stripped.startswith("# "):
                continue
            if any(
                stripped.startswith(p)
                for p in (
                    "**Source:**",
                    "Source:",
                    "**Duration:**",
                    "Duration:",
                    "**Date:**",
                    "Date:",
                    "**Channel:**",
                    "Channel:",
                )
            ):
                continue
            if stripped == "---":
                continue
            if stripped.startswith("![[") or stripped.startswith("[["):
                continue
            if stripped.startswith(">"):
                continue
            skip_metadata = False

        # Skip horizontal rules
        if stripped == "---":
            continue

        # Skip embeds
        if stripped.startswith("![["):
            continue

        # Skip standalone timestamp attribution lines: > — *2:15* or — 0:00
        if re.match(r"^[>\s]*[—–\-]\s*\*?\d{1,2}:\d{2}(?::\d{2})?\*?\s*$", stripped):
            continue

        # Callout lines: > [!tip] Title text
        if re.match(r">\s*\[!", stripped):
            match = re.match(r">\s*\[!\w+\]\s*(.*)", stripped)
            if match and match.group(1):
                cleaned.append(match.group(1))
            continue

        # Table separator lines
        if re.match(r"\|[-:\s|]+\|", stripped):
            continue

        # Table rows — extract cell contents, skip timestamp-only cells
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            cells = [
                c for c in cells if c and not re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", c)
            ]
            if cells:
                cleaned.append(". ".join(cells))
            continue

        # Strip checklist syntax
        stripped = re.sub(r"^-\s*\[[ x]\]\s*", "", stripped)

        # Strip blockquote
        stripped = re.sub(r"^>\s*", "", stripped)

        # Strip headers with timestamp prefix: "## 5:00 — The Miami Side Quest" -> "The Miami Side Quest"
        stripped = re.sub(
            r"^#{1,6}\s+\d{1,2}:\d{2}(?::\d{2})?\s*[—–\-]\s*", "", stripped
        )

        # Strip headers (keep text)
        stripped = re.sub(r"^#{1,6}\s+", "", stripped)

        # Strip bullet points
        stripped = re.sub(r"^\s*[-*]\s+", "", stripped)

        # Strip numbered list prefixes: "**1." or "1."
        stripped = re.sub(r"^\*?\*?\d+\.\s*\*?\*?\s*", "", stripped)

        # Strip bold
        stripped = re.sub(r"\*\*(.*?)\*\*", r"\1", stripped)

        # Strip italic
        stripped = re.sub(r"\*(.*?)\*", r"\1", stripped)

        # Strip links [text](url) -> text
        stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)

        # Strip wiki links [[file|display]] -> display
        stripped = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", stripped)
        stripped = re.sub(r"\[\[([^\]]+)\]\]", r"\1", stripped)

        # Strip inline code
        stripped = re.sub(r"`([^`]+)`", r"\1", stripped)

        # Strip inline timestamps
        stripped = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", "", stripped)

        # Strip emoji and decorative unicode
        stripped = re.sub(
            r"[\U0001F300-\U0001FFFF\u2600-\u27FF\u2300-\u23FF\u2B50\u2728\u2734\u2735\u2716\u2714\u2764\u00A9\u00AE\u2122\u25A0-\u25FF]+",
            "",
            stripped,
        )
        stripped = re.sub(r"[✦✧★☆●○◆◇▶►▷▸◂◄◁◀]+", "", stripped)

        # Clean up residual artifacts: trailing/leading em dashes, double spaces
        stripped = re.sub(r"\s*[—–]\s*$", "", stripped)
        stripped = re.sub(r"^\s*[—–]\s*", "", stripped)
        stripped = re.sub(r"\s{2,}", " ", stripped)

        if stripped.strip():
            cleaned.append(stripped.strip())

    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def read_aloud(
    file_path: str,
    voice: str = "af_heart",
    speed: float = 1.0,
) -> Dict[str, Any]:
    """
    Add TTS audio to an existing notes file.

    Reads the file, strips markdown formatting, generates MP3,
    and embeds an audio player link if Obsidian is installed.

    Args:
        file_path: Path to the notes file.
        voice: Voice ID. Default: af_heart.
        speed: Speech speed multiplier. Default: 1.0.

    Returns:
        Dict with file_path, duration, embedded status.
    """
    file_path = os.path.expanduser(file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "r") as f:
        content = f.read()

    # Strip markdown for TTS
    spoken_text = _strip_markdown(content)
    if not spoken_text.strip():
        raise ValueError("No content to read after stripping metadata and formatting")

    # Generate MP3 with same name as notes file
    basename = os.path.splitext(os.path.basename(file_path))[0]
    output_dir = os.path.dirname(file_path)
    audio_filename = f"{basename}.mp3"

    result = text_to_speech(
        text=spoken_text,
        voice=voice,
        output_dir=output_dir,
        output_filename=audio_filename,
        speed=speed,
    )

    # Embed in file if Obsidian is installed
    obsidian_installed = os.path.exists("/Applications/Obsidian.app") or bool(
        shutil.which("obsidian")
    )

    if obsidian_installed:
        embed_line = f"![[{audio_filename}]]"
        tip_line = (
            "> Press Cmd+E before playing \u2014 prevents audio from pausing on scroll"
        )

        # Copy MP3 into Obsidian vault so the embed can find it
        vault_path = _find_obsidian_vault()
        if vault_path:
            mp3_source = result["file_path"]
            mp3_in_vault = os.path.join(vault_path, audio_filename)
            if os.path.abspath(mp3_source) != os.path.abspath(mp3_in_vault):
                shutil.copy2(mp3_source, mp3_in_vault)

        if embed_line not in content:
            new_content = f"{embed_line}\n{tip_line}\n\n{content}"
            with open(file_path, "w") as f:
                f.write(new_content)
            result["embedded"] = True
        else:
            result["embedded"] = False
    else:
        result["embedded"] = False

    return result
