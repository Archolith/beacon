# Beacon examples

Three small, self-contained example repositories that show Beacon being used on
different project shapes. Each is a real, runnable manifest-plus-docs directory,
not a renamed copy of Beacon's own manifest. Every example validates with zero
errors, builds a provider, and exports to a snapshot, and the test suite
(`tests/test_examples.py`) checks all of that automatically.

| Example | Shape | What it demonstrates |
| --- | --- | --- |
| [`library/`](library/) | A small Python package | A focused public API, a format spec doc, and shape-safe change guardrails. |
| [`service/`](service/) | A long-running background service | A pipeline, retry/backpressure concepts, and lifecycle guardrails. |
| [`monorepo-research/`](monorepo-research/) | A research/analysis monorepo | Immutable-data guardrails, a reproducibility concept, and a data-lineage doc. |

## How to use one

Each directory is self-contained. From inside the example directory:

```bash
cd examples/library
python -m pytest ../../tests/test_examples.py
```

To validate and inspect an example against the current core, point Beacon at its
manifest. The reference workflow is:

```text
validate -> inspect (task-aware) -> export (embedded and metadata-only)
```

## Choosing a shape

Pick the example that most resembles your repository, then copy its
`beacon.yaml` and docs and adapt the names. The three shapes cover a library, a
daemon, and a data/reporting monorepo. If yours is none of these, start from the
library example and adjust — the manifest schema is the same for every shape.

## Keeping examples healthy

- Every example must keep zero validation errors and stay publishable, so it
  continues to export cleanly.
- Do not add content that would trip the sensitive-content scanner (real tokens,
  credential URLs, or private-key blocks) — the examples are meant to be safe to
  export by default.
- `tests/test_examples.py` enumerates exactly the maintained set. Adding an
  example means adding it to that enumeration.
