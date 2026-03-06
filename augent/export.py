"""
Augent Export - Export transcriptions and matches to various formats

Supports:
- SRT (SubRip subtitle format)
- VTT (WebVTT for web players)
- CSV (spreadsheet format)
- Markdown (human-readable report)
- JSON (default structured output)
"""

import csv
import io
import json
import re
from typing import Dict, List, Optional


def format_srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    """Convert seconds to VTT timestamp format (HH:MM:SS.mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def format_simple_timestamp(seconds: float) -> str:
    """Convert seconds to simple mm:ss format."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


class Exporter:
    """Export transcriptions and matches to various formats."""

    @staticmethod
    def to_srt(
        segments: List[Dict], highlight_keywords: Optional[List[str]] = None
    ) -> str:
        """
        Export transcription segments to SRT subtitle format.

        Args:
            segments: List of segment dicts with 'start', 'end', 'text' keys
            highlight_keywords: Optional keywords to wrap in <b> tags

        Returns:
            SRT formatted string
        """
        lines = []

        for i, segment in enumerate(segments, 1):
            start = format_srt_timestamp(segment["start"])
            end = format_srt_timestamp(segment["end"])
            text = segment["text"].strip()

            # Highlight keywords if specified
            if highlight_keywords:
                for kw in highlight_keywords:
                    # Case-insensitive replacement with bold tags
                    pattern = re.compile(re.escape(kw), re.IGNORECASE)
                    text = pattern.sub(f"<b>{kw}</b>", text)

            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")  # Blank line between entries

        return "\n".join(lines)

    @staticmethod
    def to_vtt(
        segments: List[Dict], highlight_keywords: Optional[List[str]] = None
    ) -> str:
        """
        Export transcription segments to WebVTT format.

        Args:
            segments: List of segment dicts with 'start', 'end', 'text' keys
            highlight_keywords: Optional keywords to wrap in <b> tags

        Returns:
            VTT formatted string
        """
        lines = ["WEBVTT", ""]

        for i, segment in enumerate(segments, 1):
            start = format_vtt_timestamp(segment["start"])
            end = format_vtt_timestamp(segment["end"])
            text = segment["text"].strip()

            # Highlight keywords if specified
            if highlight_keywords:
                for kw in highlight_keywords:
                    pattern = re.compile(re.escape(kw), re.IGNORECASE)
                    text = pattern.sub(f"<b>{kw}</b>", text)

            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def matches_to_srt(matches: List[Dict], duration: float = 5.0) -> str:
        """
        Export keyword matches to SRT format.

        Each match becomes a subtitle entry showing the keyword and snippet.

        Args:
            matches: List of match dicts with timestamp_seconds, keyword, snippet
            duration: Duration to show each match (seconds)

        Returns:
            SRT formatted string
        """
        lines = []

        for i, match in enumerate(matches, 1):
            start_sec = match.get("timestamp_seconds", 0)
            end_sec = start_sec + duration

            start = format_srt_timestamp(start_sec)
            end = format_srt_timestamp(end_sec)

            keyword = match.get("keyword", "")
            snippet = match.get("snippet", "").replace("...", "").strip()

            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(f"[{keyword}] {snippet}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def matches_to_vtt(matches: List[Dict], duration: float = 5.0) -> str:
        """
        Export keyword matches to WebVTT format.

        Args:
            matches: List of match dicts
            duration: Duration to show each match

        Returns:
            VTT formatted string
        """
        lines = ["WEBVTT", ""]

        for i, match in enumerate(matches, 1):
            start_sec = match.get("timestamp_seconds", 0)
            end_sec = start_sec + duration

            start = format_vtt_timestamp(start_sec)
            end = format_vtt_timestamp(end_sec)

            keyword = match.get("keyword", "")
            snippet = match.get("snippet", "").replace("...", "").strip()

            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(f"[{keyword}] {snippet}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def to_csv(matches: List[Dict]) -> str:
        """
        Export matches to CSV format.

        Args:
            matches: List of match dicts

        Returns:
            CSV formatted string
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(
            [
                "keyword",
                "timestamp",
                "timestamp_seconds",
                "snippet",
                "confidence",
                "match_type",
            ]
        )

        # Data rows
        for match in matches:
            writer.writerow(
                [
                    match.get("keyword", ""),
                    match.get("timestamp", ""),
                    match.get("timestamp_seconds", 0),
                    match.get("snippet", "").replace("...", "").strip(),
                    match.get("confidence", 1.0),
                    match.get("match_type", "exact"),
                ]
            )

        return output.getvalue()

    @staticmethod
    def to_markdown(
        matches: List[Dict],
        audio_file: str = "",
        transcription_text: str = "",
        include_full_text: bool = False,
    ) -> str:
        """
        Export matches to a human-readable Markdown report.

        Args:
            matches: List of match dicts
            audio_file: Original audio file name
            transcription_text: Full transcription text
            include_full_text: Whether to include full transcription

        Returns:
            Markdown formatted string
        """
        lines = []

        # Header
        lines.append("# Augent Search Results")
        lines.append("")

        if audio_file:
            lines.append(f"**Audio File:** {audio_file}")
            lines.append("")

        # Summary
        keywords = list({m.get("keyword", "") for m in matches})
        lines.append(f"**Keywords searched:** {', '.join(keywords)}")
        lines.append(f"**Total matches:** {len(matches)}")
        lines.append("")

        # Matches by keyword
        lines.append("## Matches")
        lines.append("")

        # Group by keyword
        by_keyword: Dict[str, List[Dict]] = {}
        for match in matches:
            kw = match.get("keyword", "unknown")
            if kw not in by_keyword:
                by_keyword[kw] = []
            by_keyword[kw].append(match)

        for keyword, kw_matches in by_keyword.items():
            lines.append(f"### {keyword} ({len(kw_matches)} matches)")
            lines.append("")
            lines.append("| Timestamp | Snippet | Type |")
            lines.append("|-----------|---------|------|")

            for match in kw_matches:
                ts = match.get("timestamp", "")
                snippet = match.get("snippet", "").replace("...", "").strip()
                match_type = match.get("match_type", "exact")
                lines.append(f"| {ts} | {snippet} | {match_type} |")

            lines.append("")

        # Full transcription
        if include_full_text and transcription_text:
            lines.append("## Full Transcription")
            lines.append("")
            lines.append(transcription_text)
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def to_json(
        matches: List[Dict],
        grouped: bool = True,
        include_metadata: bool = False,
        metadata: Optional[Dict] = None,
    ) -> str:
        """
        Export matches to JSON format.

        Args:
            matches: List of match dicts
            grouped: Group matches by keyword
            include_metadata: Include additional metadata
            metadata: Optional metadata dict

        Returns:
            JSON formatted string
        """
        if grouped:
            # Group by keyword
            result: Dict[str, List[Dict]] = {}
            for match in matches:
                kw = match.get("keyword", "unknown")
                if kw not in result:
                    result[kw] = []
                result[kw].append(
                    {
                        "timestamp": match.get("timestamp", ""),
                        "timestamp_seconds": match.get("timestamp_seconds", 0),
                        "snippet": match.get("snippet", ""),
                        "confidence": match.get("confidence", 1.0),
                        "match_type": match.get("match_type", "exact"),
                    }
                )

            if include_metadata and metadata:
                return json.dumps({"metadata": metadata, "matches": result}, indent=2)

            return json.dumps(result, indent=2)
        else:
            if include_metadata and metadata:
                return json.dumps({"metadata": metadata, "matches": matches}, indent=2)

            return json.dumps(matches, indent=2)


def export_matches(matches: List[Dict], format: str = "json", **kwargs) -> str:
    """
    Export matches to the specified format.

    Args:
        matches: List of match dicts
        format: Output format (json, csv, srt, vtt, markdown)
        **kwargs: Additional arguments passed to the specific exporter

    Returns:
        Formatted string
    """
    format = format.lower()
    exporter = Exporter()

    if format == "json":
        return exporter.to_json(matches, **kwargs)
    elif format == "csv":
        return exporter.to_csv(matches)
    elif format == "srt":
        return exporter.matches_to_srt(matches, **kwargs)
    elif format == "vtt":
        return exporter.matches_to_vtt(matches, **kwargs)
    elif format in ("markdown", "md"):
        return exporter.to_markdown(matches, **kwargs)
    else:
        raise ValueError(
            f"Unknown format: {format}. Use json, csv, srt, vtt, or markdown."
        )


def export_transcription(segments: List[Dict], format: str = "srt", **kwargs) -> str:
    """
    Export full transcription to subtitle format.

    Args:
        segments: List of segment dicts with start, end, text
        format: Output format (srt, vtt)
        **kwargs: Additional arguments

    Returns:
        Formatted string
    """
    format = format.lower()
    exporter = Exporter()

    if format == "srt":
        return exporter.to_srt(segments, **kwargs)
    elif format == "vtt":
        return exporter.to_vtt(segments, **kwargs)
    else:
        raise ValueError(f"Unknown format for transcription: {format}. Use srt or vtt.")
