"""
Tests for semantic search ranking.

Validates deep_search (single-file) and _search_memory_semantic (cross-file)
using deterministic mock embeddings. No ML model loaded, no audio files on
disk. All similarity values are hardcoded snapshots so any change to ranking
logic is caught immediately.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from augent.embeddings import (
    _build_snippet,
    _highlight_keywords,
    _search_memory_semantic,
    deep_search,
)

# --- Synthetic data ---

SEGMENT_TEXTS = [
    "The brain processes dopamine signals during reward anticipation",
    "Sleep deprivation significantly reduces cognitive performance",
    "Exercise increases neuroplasticity and memory consolidation",
    "Funding challenges affect startup growth trajectories",
    "Machine learning models require substantial training data",
    "Meditation practice reduces cortisol and stress markers",
]


def _make_segments(n=6):
    """Create n synthetic segments with predictable text and 10-second spacing."""
    return [
        {
            "text": SEGMENT_TEXTS[i % len(SEGMENT_TEXTS)],
            "start": float(i * 10),
            "end": float(i * 10 + 8),
        }
        for i in range(n)
    ]


def _make_embeddings(n=6, dim=8):
    """Deterministic normalized embeddings (seed=42)."""
    rng = np.random.RandomState(42)
    emb = rng.randn(n, dim).astype(np.float32)
    return emb / np.linalg.norm(emb, axis=1, keepdims=True)


def _make_query_embedding(dim=8):
    """Deterministic query vector (seed=99)."""
    rng = np.random.RandomState(99)
    q = rng.randn(dim).astype(np.float32)
    return q / np.linalg.norm(q)


# --- Fixtures ---


@pytest.fixture
def segments():
    return _make_segments()


@pytest.fixture
def embeddings():
    return _make_embeddings()


@pytest.fixture
def query_embedding():
    return _make_query_embedding()


@pytest.fixture
def mock_embedding_model(query_embedding):
    """Mock sentence-transformer model that returns the deterministic query vector."""
    model = MagicMock()
    model.encode = (
        lambda text, convert_to_numpy=True, show_progress_bar=False: query_embedding
    )
    return model


@pytest.fixture
def deep_search_env(segments, embeddings, mock_embedding_model):
    """Patch all external dependencies for deep_search calls."""

    class _MockMemory:
        def hash_audio_file(self, path):
            return "fakehash_deep"

        def get_embeddings(self, audio_hash, model_name):
            return {"embeddings": embeddings}

        def set_embeddings(self, *args, **kwargs):
            pass

    with (
        patch("os.path.exists", return_value=True),
        patch("augent.embeddings.get_transcription_memory", return_value=_MockMemory()),
        patch(
            "augent.embeddings.transcribe_audio",
            return_value={
                "segments": segments,
                "duration": 60.0,
                "language": "en",
                "cached": True,
            },
        ),
        patch("augent.embeddings._get_or_compute_embeddings", return_value=embeddings),
        patch("augent.embeddings._get_embedding_model_cache") as mock_cache,
    ):
        mock_cache.return_value.get.return_value = mock_embedding_model
        yield


@pytest.fixture
def memory_entries(embeddings):
    """Two synthetic transcription files with non-overlapping timestamps."""
    segs_a = _make_segments(3)
    segs_b = _make_segments(3)
    for s in segs_b:
        s["start"] += 100
        s["end"] += 100

    return [
        {
            "audio_hash": "hash_a",
            "title": "Podcast A",
            "file_path": "/fake/podcast_a.mp3",
            "segments": segs_a,
            "embeddings": embeddings[:3],
            "segment_count": 3,
        },
        {
            "audio_hash": "hash_b",
            "title": "Podcast B",
            "file_path": "/fake/podcast_b.mp3",
            "segments": segs_b,
            "embeddings": embeddings[3:],
            "segment_count": 3,
        },
    ]


@pytest.fixture
def memory_search_env(mock_embedding_model):
    """Patch external dependencies for _search_memory_semantic calls."""
    with (
        patch("augent.embeddings._get_or_compute_embeddings"),
        patch("augent.embeddings._get_embedding_model_cache") as mock_cache,
    ):
        mock_cache.return_value.get.return_value = mock_embedding_model
        yield


# --- deep_search (single file) ---


class TestDeepSearch:
    """Regression tests for single-file semantic search."""

    def test_ranking_produces_exact_snapshot(self, deep_search_env):
        result = deep_search(
            "/fake/audio.mp3", "exercise neuroplasticity memory", top_k=3
        )

        assert result["query"] == "exercise neuroplasticity memory"
        assert result["total_segments"] == 6
        assert result["cached"] is True
        assert len(result["results"]) == 3

        for r in result["results"]:
            assert set(r.keys()) == {"start", "end", "text", "timestamp", "similarity"}
            assert isinstance(r["similarity"], float)
            assert 0.0 <= r["similarity"] <= 1.0

        sims = [r["similarity"] for r in result["results"]]
        assert sims == sorted(
            sims, reverse=True
        ), "Results must be descending by similarity"
        assert sims == [0.5518, 0.2502, 0.1047]
        assert [r["start"] for r in result["results"]] == [0.0, 30.0, 50.0]

    def test_dedup_reduces_overlapping_results(self, deep_search_env):
        no_dedup = deep_search(
            "/fake/audio.mp3", "exercise neuroplasticity", top_k=6, dedup_seconds=0
        )
        with_dedup = deep_search(
            "/fake/audio.mp3", "exercise neuroplasticity", top_k=6, dedup_seconds=15
        )

        assert len(with_dedup["results"]) <= len(no_dedup["results"])

    def test_empty_transcription_returns_no_results(self):
        with (
            patch("os.path.exists", return_value=True),
            patch("augent.embeddings.get_transcription_memory"),
            patch(
                "augent.embeddings.transcribe_audio",
                return_value={
                    "segments": [],
                    "duration": 0,
                    "cached": False,
                },
            ),
        ):
            result = deep_search("/fake/audio.mp3", "anything")

        assert result["results"] == []
        assert result["total_segments"] == 0


# --- _search_memory_semantic (cross-file) ---


class TestSearchMemorySemantic:
    """Regression tests for cross-file semantic search."""

    def test_ranking_produces_exact_snapshot(self, memory_search_env, memory_entries):
        result = _search_memory_semantic(
            "exercise neuroplasticity memory",
            top_k=3,
            entries=memory_entries,
        )

        assert result["query"] == "exercise neuroplasticity memory"
        assert result["mode"] == "semantic"
        assert result["files_searched"] == 2
        assert result["total_segments"] == 6
        assert len(result["results"]) == 3

        expected_keys = {
            "title",
            "file_path",
            "start",
            "end",
            "text",
            "timestamp",
            "similarity",
        }
        for r in result["results"]:
            assert set(r.keys()) == expected_keys

        sims = [r["similarity"] for r in result["results"]]
        assert sims == sorted(
            sims, reverse=True
        ), "Results must be descending by similarity"
        assert sims == [0.5518, 0.2502, 0.1047]
        assert [r["title"] for r in result["results"]] == [
            "Podcast A",
            "Podcast B",
            "Podcast B",
        ]
        assert [r["start"] for r in result["results"]] == [0.0, 100.0, 120.0]

    def test_dedup_merges_within_time_window(self, memory_search_env, memory_entries):
        no_dedup = _search_memory_semantic(
            "exercise", top_k=6, entries=memory_entries, dedup_seconds=0
        )
        with_dedup = _search_memory_semantic(
            "exercise", top_k=6, entries=memory_entries, dedup_seconds=15
        )

        assert len(with_dedup["results"]) <= len(no_dedup["results"])

    def test_empty_memory_returns_no_results(self):
        result = _search_memory_semantic("anything", top_k=5, entries=[])

        assert result["results"] == []
        assert result["total_segments"] == 0
        assert result["files_searched"] == 0


# --- Shared helpers ---


class TestHighlightKeywords:
    """Tests for _highlight_keywords bold wrapping."""

    def test_wraps_all_provided_keywords(self):
        text = "The brain processes dopamine signals"
        result = _highlight_keywords(text, ["brain", "dopamine", "The"])
        assert "**brain**" in result
        assert "**dopamine**" in result
        assert "**The**" in result

    def test_preserves_unmatched_text(self):
        text = "No keywords here"
        result = _highlight_keywords(text, ["missing"])
        assert result == "No keywords here"

    def test_case_insensitive_matching(self):
        text = "The BRAIN processes signals"
        result = _highlight_keywords(text, ["brain"])
        assert "**BRAIN**" in result


class TestBuildSnippet:
    """Tests for _build_snippet context expansion."""

    def test_center_segment_includes_neighbors(self, segments):
        snippet = _build_snippet(segments, 2, target_words=10)
        assert len(snippet.split()) >= 5

    def test_first_segment_has_no_leading_ellipsis(self, segments):
        snippet = _build_snippet(segments, 0, target_words=10)
        assert not snippet.startswith("...")

    def test_last_segment_has_no_trailing_ellipsis_when_short(self, segments):
        snippet = _build_snippet(segments, len(segments) - 1, target_words=100)
        assert not snippet.endswith("...")
