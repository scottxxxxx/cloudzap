# Contributing to CloudZap

Thanks for your interest in contributing! This guide will help you get started.

## Getting Started

1. Fork the repo and clone your fork
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in at least `CZ_JWT_SECRET` and `CZ_APPLE_BUNDLE_ID`
4. Run the test suite to confirm everything works:
   ```bash
   pytest tests/ -v
   ```

## Development Workflow

1. Create a branch from `main` for your change
2. Write tests for new functionality
3. Make your changes
4. Run tests: `pytest tests/ -v`
5. Run the app locally to verify: `uvicorn app.main:app --reload`
6. Open a pull request against `main`

## Code Style

- Python 3.12+ with type hints
- Use `async`/`await` for IO-bound operations
- Pydantic models for request/response validation
- Keep functions focused and small
- No ORM — raw SQL via aiosqlite for now

## What We're Looking For

- Bug fixes with test coverage
- New LLM provider adapters (follow the pattern in `app/services/providers/`)
- Improved error handling and edge cases
- Documentation improvements
- Performance improvements

## Pull Request Guidelines

- Keep PRs focused — one feature or fix per PR
- Include tests for new functionality
- Update the README if you're adding user-facing features
- Update the CHANGELOG under "Unreleased"

## Adding a New Provider

1. Determine if it uses the OpenAI chat completions format (many do)
   - If yes: add it to `config/providers.yml` — no code changes needed
   - If no: create a new adapter in `app/services/providers/` following `base.py`
2. Add the adapter class to `ADAPTER_MAP` in `app/services/provider_router.py`
3. Add the provider's env key to `app/config.py` and `.env.example`
4. Add tests in `tests/test_providers.py`

## Reporting Issues

- Use the GitHub issue templates (bug report or feature request)
- Include steps to reproduce for bugs
- For security issues, see `SECURITY.md`

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
