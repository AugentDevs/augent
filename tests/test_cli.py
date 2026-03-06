"""Tests for the CLI argument parsing and subcommand routing."""

from io import StringIO
from unittest import mock

import pytest

from augent.cli import _strip_quarantine, main, print_progress
from augent.core import TranscriptionProgress


class TestPrintProgress:
    def test_quiet_suppresses_output(self):
        progress = TranscriptionProgress(
            status="loading_model", progress=0.5, message="Loading..."
        )
        with mock.patch("sys.stderr", new_callable=StringIO) as err:
            print_progress(progress, quiet=True)
            assert err.getvalue() == ""

    def test_loading_model_prints_to_stderr(self):
        progress = TranscriptionProgress(
            status="loading_model", progress=0.5, message="Loading tiny model"
        )
        with mock.patch("sys.stderr", new_callable=StringIO) as err:
            print_progress(progress, quiet=False)
            assert "Loading tiny model" in err.getvalue()

    def test_transcribing_prints_to_stderr(self):
        progress = TranscriptionProgress(
            status="transcribing", progress=0.3, message="Transcribing 30%"
        )
        with mock.patch("sys.stderr", new_callable=StringIO) as err:
            print_progress(progress, quiet=False)
            assert "Transcribing 30%" in err.getvalue()

    def test_segment_prints_with_newline(self):
        progress = TranscriptionProgress(
            status="segment", progress=0.8, message="Hello world"
        )
        with mock.patch("sys.stderr", new_callable=StringIO) as err:
            print_progress(progress, quiet=False)
            assert err.getvalue().startswith("\n")
            assert "Hello world" in err.getvalue()

    def test_complete_prints_with_newline(self):
        progress = TranscriptionProgress(
            status="complete", progress=1.0, message="Done"
        )
        with mock.patch("sys.stderr", new_callable=StringIO) as err:
            print_progress(progress, quiet=False)
            assert "Done" in err.getvalue()


class TestStripQuarantine:
    @mock.patch("augent.cli.platform")
    @mock.patch("augent.cli.subprocess")
    def test_runs_xattr_on_darwin(self, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Darwin"
        _strip_quarantine("/tmp/test.csv")
        mock_subprocess.run.assert_called_once()
        args = mock_subprocess.run.call_args[0][0]
        assert args[0] == "xattr"
        assert "/tmp/test.csv" in args

    @mock.patch("augent.cli.platform")
    @mock.patch("augent.cli.subprocess")
    def test_skips_on_linux(self, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Linux"
        _strip_quarantine("/tmp/test.csv")
        mock_subprocess.run.assert_not_called()


class TestParserSubcommands:
    """Test that the CLI parser accepts all documented subcommands and options."""

    def _parse(self, args_str):
        """Parse args by invoking main() with mocked sys.argv and catching the dispatch."""
        args_list = args_str.split()
        with mock.patch("sys.argv", ["augent"] + args_list):
            # We need to intercept after parsing but before execution.
            # Easiest: mock the command handlers so they just record args.
            with mock.patch("augent.cli.cmd_search") as m:
                m.side_effect = lambda a: setattr(self, "_parsed", a)
                with mock.patch("augent.cli.cmd_transcribe") as mt:
                    mt.side_effect = lambda a: setattr(self, "_parsed", a)
                    with mock.patch("augent.cli.cmd_proximity") as mp:
                        mp.side_effect = lambda a: setattr(self, "_parsed", a)
                        with mock.patch("augent.cli.cmd_memory") as mm:
                            mm.side_effect = lambda a: setattr(self, "_parsed", a)
                            with mock.patch("augent.cli.cmd_help") as mh:
                                mh.side_effect = lambda a: setattr(self, "_parsed", a)
                                main()
        return self._parsed

    def test_search_basic(self):
        args = self._parse("search audio.mp3 keyword1,keyword2")
        assert args.command == "search"
        assert args.audio == ["audio.mp3"]
        assert args.keywords == "keyword1,keyword2"
        assert args.model == "tiny"
        assert args.format == "json"

    def test_search_with_options(self):
        args = self._parse(
            "search audio.mp3 kw --model base --format csv --output out.csv --workers 4 --quiet"
        )
        assert args.model == "base"
        assert args.format == "csv"
        assert args.output == "out.csv"
        assert args.workers == 4
        assert args.quiet is True

    def test_transcribe_basic(self):
        args = self._parse("transcribe audio.mp3")
        assert args.command == "transcribe"
        assert args.audio == "audio.mp3"
        assert args.model == "tiny"

    def test_transcribe_with_options(self):
        args = self._parse(
            "transcribe audio.mp3 --model small --format srt --output sub.srt"
        )
        assert args.model == "small"
        assert args.format == "srt"
        assert args.output == "sub.srt"

    def test_proximity_basic(self):
        args = self._parse("proximity audio.mp3 startup funding")
        assert args.command == "proximity"
        assert args.keyword1 == "startup"
        assert args.keyword2 == "funding"
        assert args.distance == 30

    def test_proximity_with_distance(self):
        args = self._parse("proximity audio.mp3 problem solution --distance 50")
        assert args.distance == 50

    def test_memory_stats(self):
        args = self._parse("memory stats")
        assert args.command == "memory"
        assert args.memory_action == "stats"

    def test_memory_clear(self):
        args = self._parse("memory clear")
        assert args.memory_action == "clear"

    def test_memory_search(self):
        args = self._parse("memory search queryterm --top-k 5 --semantic")
        assert args.memory_action == "search"
        assert args.search_query == "queryterm"
        assert args.top_k == 5
        assert args.semantic is True

    def test_help_command(self):
        args = self._parse("help")
        assert args.command == "help"


class TestMainEntryPoints:
    def test_no_args_shows_help_and_exits(self):
        with mock.patch("sys.argv", ["augent"]):
            with mock.patch("augent.cli.print_simple_help") as mock_help:
                with pytest.raises(SystemExit) as exc:
                    main()
                assert exc.value.code == 0
                mock_help.assert_called_once()

    def test_dash_h_shows_help_and_exits(self):
        with mock.patch("sys.argv", ["augent", "-h"]):
            with mock.patch("augent.cli.print_simple_help") as mock_help:
                with pytest.raises(SystemExit) as exc:
                    main()
                assert exc.value.code == 0
                mock_help.assert_called_once()
