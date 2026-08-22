# Contributing to GraphGPT

Thank you for helping make declarative LangGraph applications easier to build and share.

## Start here

1. Search existing issues and discussions before opening a new proposal.
2. Use an issue form for reproducible bugs or feature requests.
3. Keep changes focused; public DSL, IR, CLI, and plugin protocol changes require an RFC issue first.
4. Add tests for behavior changes and update compatibility notes when dependency support changes.

## Development

```bash
git clone https://github.com/BrucePayton/GraphGPT.git
cd GraphGPT
uv sync --extra dev --extra langchain --extra cli
uv run ruff check .
uv run mypy
uv run pytest --cov=graphgpt --cov-fail-under=90
uv build
```

Python 3.11 and 3.13 are tested in CI. Avoid importing user code during `validate` or weakening the
YAML loader, module allowlist, secret-reference policy, or plugin isolation boundaries.

## Plugins and integrations

Create a standalone plugin with:

```bash
graphgpt plugin init ./graphgpt-my-plugin --name my-plugin
```

Plugin packages should test their manifest and every advertised capability. See
[`docs/PLUGINS.md`](docs/PLUGINS.md) before submitting a plugin to [`ECOSYSTEM.md`](ECOSYSTEM.md).
GraphGPT does not vendor provider SDKs into its core package.

## Pull requests

- Use a descriptive title and explain the user-visible outcome.
- Link the issue or RFC when one exists.
- Include verification commands and compatibility impact.
- Preserve deterministic IR output and stable diagnostic codes.
- Add a changelog entry for user-facing behavior.

Maintainers may ask that large changes be split into independently reviewable pull requests. By
participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
