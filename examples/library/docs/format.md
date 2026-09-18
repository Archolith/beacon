# Front-matter format notes

This document defines exactly what frontmatter-kit accepts and preserves. It is
the reference for the parser and the writer, and the canonical source the agent
should read before changing either.

## The leading block

A front-matter block starts at the very first line of a file with a line whose
content is exactly `---`. It ends at the next line whose content is exactly
`---` or `...`. Everything between the two markers is YAML and must parse.

## What is preserved

The library records the exact text of the block so a write can preserve:

- line endings (LF or CRLF, chosen by the original file),
- blank lines inside the block, and
- the author's scalar quoting style where the value is unchanged.

Preservation is what makes a no-op write a true no-op: if the record is
unchanged, the output bytes equal the input bytes.

## What is normalized

Only the values the caller actually changes are re-serialized. Unchanged keys
are kept byte-for-byte from the source block. This means round trips are
predictable and diffs stay small.

## Delimiters

The start marker must be `---` on its own line. The closing marker may be `---`
or `...`. A file without a leading block is treated as an empty record and can
be written back the same way.

## Validation

Parsed values are validated against the record schema. A block that does not
match the expected shape raises a clear error rather than silently coercing
types, so callers never see a half-interpreted record.
