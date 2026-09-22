# Analysis methodology

How tide-tables turns uneven tide-gauge records into trend estimates.

## Inputs and units

Each station contributes a time series of water-level observations relative to
its own local datum. Stations use different datums and different sampling
cadences, so nothing is compared before normalization.

## Cleaning pipeline

Every record passes through the same deterministic steps in order:

1. **Datum alignment.** Convert each observation to a common vertical reference
   using the documented datum offset for that station.
2. **Gap handling.** Missing samples are flagged, and short gaps are filled with
   a documented rule; long gaps are left flagged and excluded from the trend.
3. **Outlier checks.** Extreme spikes are reviewed against neighboring samples
   and metadata rather than removed silently.

Cleaning never modifies a raw file. It writes derived copies to a scratch
location so the provenance of every value is traceable.

## Trend estimation

The cleaned, gap-aware series feeds a linear regression on the deseasonalized
monthly means. The output is a rate of relative sea-level change with an
uncertainty band, plus the station metadata needed to interpret it.

## Reproducibility

Results are reproducible because the environment is pinned in
`requirements.txt` and every dataset's source is documented in `docs/data.md`.
Two runs on the same inputs produce byte-identical derived data and figures.
