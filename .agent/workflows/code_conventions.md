# Code Conventions — beacon

No linter or formatter is configured yet (`pyproject.toml` has no `[tool.ruff]` /
`[tool.black]` / `[tool.mypy]` section). These are the conventions actually followed in
`src/beacon/`, not enforced rules — match them when adding code until tooling is added.

## Style

- `from __future__ import annotations` as the first import in every module.
- A one-line module docstring stating the file's single responsibility
  (e.g. `"""MCP server: tool registration and process wiring for Beacon."""`).
- Type hints on every public function signature, including return types.
- All data types are `@dataclass(frozen=True)` — no Pydantic, no ORM, no mutable
  shared state. `beacon.core.schema.to_payload()` is the one serialization path
  (`dataclasses.asdict()`), so new types don't need custom `to_dict`/`to_json` methods.
- Errors return structured JSON payloads from `BeaconBaseTool.execute()` rather than
  propagating exceptions to the MCP client — tools always respond, never crash the call.

## Naming

- `snake_case` for functions and variables, `PascalCase` for classes.
- Private module-level helpers are prefixed `_` (`_getenv`, `_hr`, `_section`, `_trunc`,
  `_json_default`) and never exported.
- MCP tool classes are named `<Verb><Noun>Tool` (e.g. `ExplainConceptTool`) and set a
  `name` class attribute matching the registered tool name, always prefixed `beacon_`
  (`beacon_explain_concept`).
- Manifest/schema dataclasses are prefixed `Beacon` (`BeaconManifest`, `BeaconConcept`,
  `BeaconSource`); answer-contract dataclasses are not (`ProjectOverview`, `SearchResult`).

## File Organization

- `core/` — pure logic with no MCP dependency: `schema.py` (types), `loader.py` (YAML →
  `BeaconManifest`), `validator.py` (semantic checks), `doc_index.py` (heading-chunked
  search). Safe to unit-test without a server.
- `provider/` — `base.py` defines the `BeaconProvider` `Protocol`; each concrete
  implementation (`manifest_provider.py`) is a separate module so a future
  `MenhirBeaconProvider` drops in without touching `core/` or `mcp/`.
- `mcp/tools/` — one file per tool, one class per file, each subclassing
  `BeaconBaseTool`. New tools are added to `ALL_TOOLS` in `mcp/tools/__init__.py` and to
  `always_visible` in `mcp/server.py` — see `.agent/architecture.md` § "Adding a New
  Tool" for the full checklist.
- `main.py` is the only place that touches `typer`, `sys`, or process-level concerns
  (logging setup, UTF-8 stdout reconfiguration); it stays a thin CLI wrapper over
  `core`/`provider`/`mcp`.

## Testing

- `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"` in `pyproject.toml` — no
  `@pytest.mark.asyncio` needed on individual tests).
- One test file per layer, not per source file: `test_core.py` (schema/loader/validator/
  doc_index), `test_provider.py` (`ManifestBeaconProvider`), `test_cli.py` (typer
  subcommands via `typer.testing.CliRunner` or equivalent).
- All tests run fully offline — no network, no LLM calls, no external services — matching
  the project's "no LLM generation at runtime" design (`.agent/architecture.md`).
- `beacon.yaml` at the repo root is a real, self-referential manifest (describes beacon
  itself), so `beacon validate`/`beacon inspect` and CLI tests have a working fixture
  without needing a separate test-only manifest.
