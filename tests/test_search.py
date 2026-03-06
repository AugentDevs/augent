"""Tests for the search module."""

from augent.search import (
    KeywordSearcher,
    clean_word,
    find_keyword_matches,
    format_timestamp,
    search_with_proximity,
)

# Sample word data for testing
SAMPLE_WORDS = [
    {"word": "The", "start": 0.0, "end": 0.2},
    {"word": "startup", "start": 0.3, "end": 0.7},
    {"word": "raised", "start": 0.8, "end": 1.1},
    {"word": "significant", "start": 1.2, "end": 1.7},
    {"word": "funding", "start": 1.8, "end": 2.2},
    {"word": "last", "start": 2.3, "end": 2.5},
    {"word": "year", "start": 2.6, "end": 2.9},
    {"word": "and", "start": 3.0, "end": 3.1},
    {"word": "they're", "start": 3.2, "end": 3.5},
    {"word": "gonna", "start": 3.6, "end": 3.9},
    {"word": "expand", "start": 4.0, "end": 4.4},
    {"word": "into", "start": 4.5, "end": 4.7},
    {"word": "new", "start": 4.8, "end": 5.0},
    {"word": "markets", "start": 5.1, "end": 5.5},
    {"word": "with", "start": 5.6, "end": 5.8},
    {"word": "the", "start": 5.9, "end": 6.0},
    {"word": "money.", "start": 6.1, "end": 6.5},
]


class TestFormatTimestamp:
    """Tests for timestamp formatting."""

    def test_format_seconds_only(self):
        assert format_timestamp(45.0) == "0:45"

    def test_format_minutes_and_seconds(self):
        assert format_timestamp(125.0) == "2:05"

    def test_format_zero(self):
        assert format_timestamp(0.0) == "0:00"

    def test_format_large_value(self):
        assert format_timestamp(3661.0) == "61:01"


class TestCleanWord:
    """Tests for word cleaning."""

    def test_removes_punctuation(self):
        assert clean_word("hello!") == "hello"
        assert clean_word("'quoted'") == "quoted"
        assert clean_word("end.") == "end"

    def test_lowercases(self):
        assert clean_word("HELLO") == "hello"
        assert clean_word("HeLLo") == "hello"

    def test_handles_empty(self):
        assert clean_word("") == ""

    def test_handles_only_punctuation(self):
        assert clean_word("...") == ""


class TestKeywordSearcher:
    """Tests for the KeywordSearcher class."""

    def test_exact_match_single_word(self):
        searcher = KeywordSearcher()
        matches = searcher.search_exact(SAMPLE_WORDS, ["startup"])

        assert len(matches) == 1
        assert matches[0].keyword == "startup"
        assert matches[0].timestamp == "0:00"
        assert "startup" in matches[0].snippet.lower()

    def test_exact_match_multiple_keywords(self):
        searcher = KeywordSearcher()
        matches = searcher.search_exact(SAMPLE_WORDS, ["startup", "funding"])

        assert len(matches) == 2
        keywords_found = {m.keyword for m in matches}
        assert keywords_found == {"startup", "funding"}

    def test_exact_match_partial(self):
        """Test that partial matches within words are found."""
        searcher = KeywordSearcher()
        matches = searcher.search_exact(SAMPLE_WORDS, ["fund"])

        assert len(matches) == 1
        assert matches[0].keyword == "fund"

    def test_exact_match_case_insensitive(self):
        searcher = KeywordSearcher()
        matches = searcher.search_exact(SAMPLE_WORDS, ["STARTUP"])

        assert len(matches) == 1
        assert matches[0].keyword == "startup"

    def test_no_match(self):
        searcher = KeywordSearcher()
        matches = searcher.search_exact(SAMPLE_WORDS, ["nonexistent"])

        assert len(matches) == 0

    def test_context_words(self):
        """Test that context snippets include surrounding words."""
        searcher = KeywordSearcher(context_words=3)
        matches = searcher.search_exact(SAMPLE_WORDS, ["funding"])

        assert len(matches) == 1
        snippet = matches[0].snippet.lower()
        # Should include words before and after
        assert "significant" in snippet or "last" in snippet

    def test_default_context_words_is_12(self):
        """Test that default context_words is 12 (~25 words total)."""
        searcher = KeywordSearcher()
        assert searcher.context_words == 12


class TestProximitySearch:
    """Tests for proximity search."""

    def test_finds_nearby_keywords(self):
        searcher = KeywordSearcher()
        matches = searcher.search_proximity(
            SAMPLE_WORDS, "startup", "funding", max_distance=10
        )

        assert len(matches) >= 1
        assert "near" in matches[0].keyword

    def test_respects_max_distance(self):
        searcher = KeywordSearcher()

        # With large distance - should find
        matches_large = searcher.search_proximity(
            SAMPLE_WORDS, "startup", "money", max_distance=20
        )

        # With small distance - might not find
        matches_small = searcher.search_proximity(
            SAMPLE_WORDS, "startup", "money", max_distance=2
        )

        assert len(matches_large) >= len(matches_small)

    def test_no_proximity_match(self):
        searcher = KeywordSearcher()
        matches = searcher.search_proximity(
            SAMPLE_WORDS, "nonexistent1", "nonexistent2", max_distance=10
        )

        assert len(matches) == 0


class TestFindKeywordMatches:
    """Tests for the convenience function."""

    def test_returns_dict_format(self):
        matches = find_keyword_matches(SAMPLE_WORDS, ["startup"])

        assert len(matches) == 1
        assert "keyword" in matches[0]
        assert "timestamp" in matches[0]
        assert "snippet" in matches[0]

    def test_custom_context(self):
        matches = find_keyword_matches(SAMPLE_WORDS, ["funding"], context_words=5)

        assert len(matches) == 1
        # Longer context should have more words
        assert len(matches[0]["snippet"].split()) > 3


class TestSearchWithProximity:
    """Tests for the proximity convenience function."""

    def test_returns_dict_format(self):
        matches = search_with_proximity(
            SAMPLE_WORDS, "startup", "funding", max_distance=10
        )

        assert isinstance(matches, list)
        if len(matches) > 0:
            assert "keyword" in matches[0]
            assert "timestamp" in matches[0]
            assert "match_type" in matches[0]
            assert matches[0]["match_type"] == "proximity"


class TestMultiWordPhrases:
    """Tests for multi-word phrase matching."""

    def test_phrase_match(self):
        searcher = KeywordSearcher()
        matches = searcher.search_exact(SAMPLE_WORDS, ["last year"])

        assert len(matches) == 1
        assert matches[0].keyword == "last year"
        assert matches[0].match_type == "phrase"

    def test_phrase_no_match(self):
        searcher = KeywordSearcher()
        matches = searcher.search_exact(SAMPLE_WORDS, ["next year"])

        assert len(matches) == 0
