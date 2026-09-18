# frontmatter-kit

Parse and write the YAML front matter at the top of Markdown files.

This is a small, dependency-light Python library. It reads the YAML block
between the leading `---` markers of a Markdown file, gives you a typed
`Record`, and can write an updated block back without touching the body below.

## Why it exists

Markdown files carry metadata in a leading YAML block. Tools that edit that
block usually re-serialize the whole file, which throws away the author's
formatting and line endings. frontmatter-kit isolates that one concern so
editing metadata is safe and reviewable.

## Quick example

```python
from pathlib import Path
from frontmatter_kit import load, dump

record = load(Path("note.md"))
record.meta["tags"] = ["reference"]
dump(Path("note.md"), record)
```

`dump` writes atomically and skips the write entirely when the record is
unchanged, so repeated runs leave the file byte-identical.

## What it does not do

It is not a general YAML parser, and it is not a CLI. It only handles the
leading block between the first pair of `---` markers. See
[docs/format.md](docs/format.md) for the exact format it accepts.

## Development

```bash
python -m pip install -e .
python -m pytest tests/
```

All tests run offline. Add `examples/library` as a maintained Beacon example:
the manifest lives in `beacon.yaml` and references `README.md` and
`docs/format.md`.
