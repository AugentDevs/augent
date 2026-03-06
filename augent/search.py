"""
Augent Search - Keyword search with exact and proximity matching

Provides search capabilities including:
- Exact keyword matching
- Multi-word phrase matching
- Proximity search (find keywords near each other)
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class Match:
    """A keyword match result."""

    keyword: str
    timestamp: str
    timestamp_seconds: float
    snippet: str
    confidence: float = 1.0
    match_type: str = "exact"


def format_timestamp(seconds: float) -> str:
    """Convert seconds to mm:ss format."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def clean_word(word: str) -> str:
    """Clean a word for comparison."""
    return word.lower().strip(".,!?;:'\"()-[]{}").strip()


def highlight_keywords(text: str, keywords: List[str]) -> str:
    """Wrap keyword occurrences in **bold** markers for terminal display."""
    for kw in keywords:
        if not kw or not kw.strip():
            continue
        pattern = re.compile(r"(" + re.escape(kw) + r")", re.IGNORECASE)
        text = pattern.sub(r"**\1**", text)
    return text


def get_context(
    words: List[Dict],
    center_idx: int,
    context_words: int = 12,
    end_idx: Optional[int] = None,
) -> str:
    """Extract context snippet around a word index."""
    if end_idx is None:
        end_idx = center_idx

    start = max(0, center_idx - context_words)
    end = min(len(words), end_idx + context_words + 1)
    context = " ".join(w["word"] for w in words[start:end])
    return f"...{context}..."


class KeywordSearcher:
    """
    Keyword search engine for transcriptions.

    Supports exact matching, phrase matching, and proximity-based search.
    """

    def __init__(self, context_words: int = 12):
        """
        Initialize the searcher.

        Args:
            context_words: Number of words to include for context snippets
        """
        self.context_words = context_words

    def search_exact(self, words: List[Dict], keywords: List[str]) -> List[Match]:
        """
        Search for exact keyword matches.

        Args:
            words: List of word dicts with 'word', 'start', 'end' keys
            keywords: List of keywords to search for

        Returns:
            List of Match objects
        """
        matches = []
        lower_keywords = [k.lower() for k in keywords]

        for i, word_obj in enumerate(words):
            current_word = clean_word(word_obj["word"])

            for keyword in lower_keywords:
                keyword_parts = keyword.split()

                if len(keyword_parts) == 1:
                    if keyword in current_word or current_word == keyword:
                        snippet = get_context(words, i, self.context_words)
                        snippet = highlight_keywords(snippet, [keyword])
                        matches.append(
                            Match(
                                keyword=keyword,
                                timestamp=format_timestamp(word_obj["start"]),
                                timestamp_seconds=word_obj["start"],
                                snippet=snippet,
                                confidence=1.0,
                                match_type="exact",
                            )
                        )
                else:
                    if self._match_phrase(words, i, keyword_parts):
                        snippet = get_context(
                            words,
                            i,
                            self.context_words,
                            end_idx=i + len(keyword_parts) - 1,
                        )
                        snippet = highlight_keywords(snippet, [keyword])
                        matches.append(
                            Match(
                                keyword=keyword,
                                timestamp=format_timestamp(word_obj["start"]),
                                timestamp_seconds=word_obj["start"],
                                snippet=snippet,
                                confidence=1.0,
                                match_type="phrase",
                            )
                        )

        return matches

    def search_proximity(
        self, words: List[Dict], keyword1: str, keyword2: str, max_distance: int = 30
    ) -> List[Match]:
        """
        Find occurrences where keyword1 appears within max_distance words of keyword2.
        """
        matches = []
        keyword1_lower = keyword1.lower()
        keyword2_lower = keyword2.lower()

        keyword1_positions = []
        keyword2_positions = []

        for i, word_obj in enumerate(words):
            clean = clean_word(word_obj["word"])
            if keyword1_lower in clean:
                keyword1_positions.append(i)
            if keyword2_lower in clean:
                keyword2_positions.append(i)

        for pos1 in keyword1_positions:
            for pos2 in keyword2_positions:
                distance = abs(pos1 - pos2)
                if 0 < distance <= max_distance:
                    start_idx = min(pos1, pos2)
                    end_idx = max(pos1, pos2)

                    snippet = get_context(words, start_idx, 2, end_idx)
                    snippet = highlight_keywords(snippet, [keyword1, keyword2])
                    matches.append(
                        Match(
                            keyword=f"{keyword1} near {keyword2}",
                            timestamp=format_timestamp(words[pos1]["start"]),
                            timestamp_seconds=words[pos1]["start"],
                            snippet=snippet,
                            confidence=1.0 - (distance / max_distance) * 0.3,
                            match_type="proximity",
                        )
                    )

        seen = set()
        unique_matches = []
        for m in matches:
            key = (m.keyword, m.timestamp)
            if key not in seen:
                seen.add(key)
                unique_matches.append(m)

        return unique_matches

    def _match_phrase(
        self, words: List[Dict], start_idx: int, phrase_parts: List[str]
    ) -> bool:
        """Check if a multi-word phrase matches starting at start_idx."""
        if start_idx + len(phrase_parts) > len(words):
            return False

        for j, part in enumerate(phrase_parts):
            check_word = clean_word(words[start_idx + j]["word"])
            if part not in check_word and check_word != part:
                return False

        return True

    def search(
        self,
        words: List[Dict],
        keywords: List[str],
        proximity_pairs: Optional[List[Tuple[str, str, int]]] = None,
    ) -> List[Match]:
        """
        Search for keywords.

        Args:
            words: List of word dicts
            keywords: List of keywords to search for
            proximity_pairs: List of (keyword1, keyword2, max_distance) tuples

        Returns:
            List of all matches, sorted by timestamp
        """
        all_matches = []
        all_matches.extend(self.search_exact(words, keywords))

        if proximity_pairs:
            for kw1, kw2, distance in proximity_pairs:
                all_matches.extend(self.search_proximity(words, kw1, kw2, distance))

        all_matches.sort(key=lambda m: m.timestamp_seconds)
        return all_matches


def find_keyword_matches(
    words: List[Dict], keywords: List[str], context_words: int = 12
) -> List[Dict]:
    """
    Convenience function for keyword matching.

    Args:
        words: List of word dicts with 'word', 'start', 'end' keys
        keywords: List of keywords/phrases to search for
        context_words: Number of surrounding words for context

    Returns:
        List of match dicts with keyword, timestamp, snippet, etc.
    """
    searcher = KeywordSearcher(context_words=context_words)
    matches = searcher.search(words, keywords)

    return [
        {
            "keyword": m.keyword,
            "timestamp": m.timestamp,
            "timestamp_seconds": m.timestamp_seconds,
            "snippet": m.snippet,
            "confidence": m.confidence,
            "match_type": m.match_type,
        }
        for m in matches
    ]


def search_with_proximity(
    words: List[Dict],
    keyword1: str,
    keyword2: str,
    max_distance: int = 30,
    context_words: int = 12,
) -> List[Dict]:
    """
    Search for keyword1 appearing near keyword2.
    """
    searcher = KeywordSearcher(context_words=context_words)
    matches = searcher.search_proximity(words, keyword1, keyword2, max_distance)

    return [
        {
            "keyword": m.keyword,
            "timestamp": m.timestamp,
            "timestamp_seconds": m.timestamp_seconds,
            "snippet": m.snippet,
            "confidence": m.confidence,
            "match_type": m.match_type,
        }
        for m in matches
    ]
