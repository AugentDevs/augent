# Contributing to Augent

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/Augent.git
   cd Augent
   ```
3. Install in development mode:
   ```bash
   pip install -e ".[dev,all]"
   ```
4. Verify everything works:
   ```bash
   pytest tests/ -v
   ```

## Development

### Code Style

Augent uses [Black](https://github.com/psf/black) for formatting and [Ruff](https://github.com/astral-sh/ruff) for linting.

```bash
black augent/
ruff check augent/
```

### Running Tests

```bash
pytest tests/ -v --tb=short
```

Tests run on Python 3.10, 3.11, 3.12, and 3.13 via CI.

### Project Structure

```
augent/
├── mcp.py          # MCP server (all tools for Claude)
├── core.py         # Transcription engine (faster-whisper)
├── search.py       # Keyword search
├── embeddings.py   # Semantic search + chapters
├── speakers.py     # Speaker diarization
├── tts.py          # Text-to-speech (Kokoro)
├── memory.py       # Three-layer memory (SQLite)
├── cli.py          # CLI interface
├── web.py          # Web UI (FastAPI)
├── export.py       # Export formats (JSON, CSV, SRT, VTT, MD)
└── clips.py        # Audio clip extraction
```

## Submitting Changes

1. Create a branch from `main`
2. Make your changes
3. Run tests: `pytest tests/ -v`
4. Run formatting: `black augent/`
5. Push and open a pull request

### Pull Requests

- Keep PRs focused — one feature or fix per PR
- Fill out the PR template
- Ensure CI passes before requesting review

## Reporting Bugs

Use the [bug report template](https://github.com/AugentDevs/Augent/issues/new?template=bug_report.yml).

## Feature Requests

Use the [feature request template](https://github.com/AugentDevs/Augent/issues/new?template=feature_request.yml).

## Security

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.
