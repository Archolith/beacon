# Data sources and lineage

Every dataset used by tide-tables, where it came from, and how it is licensed.

## The lineage contract

Before any analysis relies on a dataset, the maintainer records four things in
this document: the source, the license, the retrieval date, and the exact
version or reference identifier. A dataset without a lineage entry is not used
in a result.

## Station records

- **Source:** public tide-gauge archives for the stations listed in `data/`.
- **License:** the original archive license applies; see each station's
  `SOURCE.txt`.
- **Retrieval:** dates are recorded per dataset at download time.
- **Storage:** raw files live under `data/` and are treated as immutable.

## Derived data

Derived and cleaned copies are produced by the pipeline and are never committed.
They are identifiable by their input digests so a result can always be traced
back to the exact raw bytes that produced it.

## Updating a dataset

To add a station, drop the raw record under `data/`, add a lineage entry here,
and add a cleaning test. The raw file itself is never edited after landing.
