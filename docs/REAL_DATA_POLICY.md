# Real-data-only execution policy

Executable research commands, CI research jobs, and persisted research artifacts must use external real-market data.

## Allowed

- public OKX market data downloaded by `run_okx_research.py`;
- an external timestamp/close CSV loaded through `run_research.py --snapshot-manifest`, where a schema-v1 manifest binds the exact file bytes, schema, observation count, timestamp boundaries, instrument declarations, and non-empty provenance;
- immutable real-exchange fixtures with provider, instrument, timeframe, timestamps, retrieval or artifact metadata, and SHA-256 provenance;
- structural mutations of a copied real-data fixture solely to test fail-closed validation, provided no performance metric or research claim is computed from altered observations.

## Not allowed

- passing a bare CSV to `run_research.py`;
- generated price series as a fallback for a research command;
- synthetic smoke-test reports or artifacts;
- classifying, ranking, or presenting a strategy using generated market prices;
- silently substituting generated data when a provider, manifest, or file is unavailable;
- treating caller-supplied provenance identifiers as independently attested when they have only passed local structural validation.

`run_research.py` therefore requires `--snapshot-manifest` and rejects the legacy `--csv`, `--timestamp-col`, and `--close-col` arguments. The loader validates path containment, exact SHA-256, declared columns and row widths, observation count, explicit timezone-aware and strictly increasing timestamps, boundary timestamps, and finite positive closes before research begins.

The manifest records a declared timeframe and provenance object but does not query an exchange or GitHub to attest those declarations, and it does not infer cadence from the timeframe string. Audit claims must retain the provider response or workflow artifact, metadata, hashes, retrieval/request details, and any independent continuity evidence needed for the declared bar interval.
