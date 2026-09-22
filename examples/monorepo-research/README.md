# tide-tables

A research and analysis monorepo over historical tide-gauge records.

This repository assembles a reproducible pipeline for estimating relative
sea-level change from multiple coastal tide-gauge stations. It mixes analysis
code, a pinned environment, raw-data references, and generated reports under
one roof, with clear boundaries so nothing accidentally mutates the inputs.

## Layout

- `data/` — raw station records, treated as immutable inputs (never edited).
- `analysis/` — normalization, gap handling, outlier checks, and trend code.
- `reports/` — generated figures and tables (git-ignored; built, not committed).
- `docs/` — the reference documents an agent should read first.
- `tests/` — offline unit tests for the pipeline steps.

## Getting started

```bash
python -m pip install -r requirements.txt
python -m pytest tests/
```

The analysis entry point runs the full pipeline over every station and writes
figures to `reports/`. Because the environment is pinned and data lineage is
documented in `docs/data.md`, the same input produces the same output.

## Why Beacon

Point a client at this directory's `beacon.yaml`. Ask the agent what the
methodology is, which files it should read before adding a new station, or what
is off-limits to touch. The manifest keeps the answers grounded in
`docs/methodology.md` and `docs/data.md` instead of a general-purpose reply.
