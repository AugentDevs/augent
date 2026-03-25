"""Tests for the config module."""

import json
import os
import tempfile

import pytest

from augent import config


class TestConfig:
    """Tests for config loading and defaults."""

    @pytest.fixture(autouse=True)
    def reset_config(self):
        """Reset the cached config before each test."""
        config._config = None
        yield
        config._config = None

    def test_defaults_exist(self):
        """All expected default keys are present."""
        expected_keys = [
            "model_size",
            "output_dir",
            "notes_output_dir",
            "clip_padding",
            "context_words",
            "tts_voice",
            "tts_speed",
            "disabled_tools",
        ]
        for key in expected_keys:
            assert key in config.DEFAULTS

    def test_default_values(self):
        """Default values are sensible."""
        assert config.DEFAULTS["model_size"] == "tiny"
        assert config.DEFAULTS["clip_padding"] == 15
        assert config.DEFAULTS["context_words"] == 25
        assert config.DEFAULTS["tts_voice"] == "af_heart"
        assert config.DEFAULTS["tts_speed"] == 1.0
        assert config.DEFAULTS["disabled_tools"] == []

    def test_get_config_returns_defaults_when_no_file(self):
        """get_config returns defaults when no config file exists."""
        # Point to nonexistent paths
        config._CONFIG_PATH = "/nonexistent/config.yaml"
        config._JSON_CONFIG_PATH = "/nonexistent/config.json"

        cfg = config.get_config()
        assert cfg["model_size"] == "tiny"
        assert cfg["tts_voice"] == "af_heart"

    def test_get_config_caches_result(self):
        """get_config returns the same dict on subsequent calls."""
        config._CONFIG_PATH = "/nonexistent/config.yaml"
        config._JSON_CONFIG_PATH = "/nonexistent/config.json"

        cfg1 = config.get_config()
        cfg2 = config.get_config()
        assert cfg1 is cfg2

    def test_json_config_overrides_defaults(self):
        """JSON config values override defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"model_size": "small", "clip_padding": 30}, f)
            f.flush()
            config._CONFIG_PATH = "/nonexistent/config.yaml"
            config._JSON_CONFIG_PATH = f.name

        try:
            cfg = config.get_config()
            assert cfg["model_size"] == "small"
            assert cfg["clip_padding"] == 30
            # Non-overridden values stay default
            assert cfg["tts_voice"] == "af_heart"
        finally:
            os.unlink(f.name)

    def test_unknown_keys_ignored(self):
        """Unknown keys in config file are silently ignored."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"model_size": "base", "unknown_key": "should_be_ignored"}, f)
            f.flush()
            config._CONFIG_PATH = "/nonexistent/config.yaml"
            config._JSON_CONFIG_PATH = f.name

        try:
            cfg = config.get_config()
            assert cfg["model_size"] == "base"
            assert "unknown_key" not in cfg
        finally:
            os.unlink(f.name)

    def test_get_single_value(self):
        """config.get() returns a single value."""
        config._CONFIG_PATH = "/nonexistent/config.yaml"
        config._JSON_CONFIG_PATH = "/nonexistent/config.json"

        assert config.get("model_size") == "tiny"
        assert config.get("clip_padding") == 15
