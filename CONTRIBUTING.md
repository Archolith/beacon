# Contributing to Beacon

Beacon is building a small, trustworthy interface between software projects and coding agents.
Changes should preserve that trust boundary: bounded local inputs, deterministic outputs, explicit
uncertainty, and no hidden network dependency.

## Before coding

- Search existing issues and the active v0.2 plans under `.agent/plans/`.
- Open an issue before a new product capability or public contract change. Small bug fixes and
  documentation corrections can go directly to a focused pull request.
- Read `AGENTS.md`, `.agent/README.md`, and `.agent/architecture.md`.
- Never include repository secrets, private document content, or credentials in issues or tests.

## Development setup

Beacon currently depends on Archolith MCP Framework v0.2.0. Until that distribution is available
from PyPI, install the tagged framework source first:

```text
git clone --branch v0.2.0 https://github.com/Archolith/archolith-mcp-framework.git ../archolith-mcp-framework
python -m pip install ../archolith-mcp-framework
python -m pip install -e ".[dev,audit]"
```

Run the core checks:

```text
python -m pytest -p no:cacheprovider -q
ruff check src tests
ruff format --check src tests
mypy --no-incremental src
bandit -r src -q
pip-audit --progress-spinner off --skip-editable
validate-pyproject pyproject.toml
python -m beacon validate beacon.yaml
python -m beacon inspect beacon.yaml
python -m build
python -m twine check dist/*
check-wheel-contents dist/*.whl
```

## Pull requests

- Keep each PR focused and explain the problem, the change, and exact verification.
- Use conventional titles such as `feat:`, `fix:`, `docs:`, `test:`, or `chore:`.
- Add positive and negative tests for behavior changes.
- Update architecture/data-model docs and `.agent/CHANGELOG.md` when contracts change.
- Do not commit build output, virtual environments, caches, or machine-local configuration.

Maintainers may ask for a design discussion before accepting changes to manifest versions, CLI/MCP
contracts, trust policy, snapshots, federation, or release infrastructure.
