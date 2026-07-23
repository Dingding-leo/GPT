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

## Verified OKX snapshot publication and recovery

`write_okx_snapshot()` verifies the source-bound normalized CSV, raw-page JSON, and metadata bytes before creating or modifying the destination. It then stages all three payloads in a temporary directory on the destination filesystem and publishes them with `os.replace` in this exact order:

1. normalized candle CSV;
2. raw-page JSON;
3. metadata JSON.

If a later replacement raises a recoverable filesystem exception, the publisher rolls already-replaced destinations back in reverse order. A file that existed before the call is restored to its exact prior bytes; a newly created file is removed. A pre-existing output directory and unrelated caller-owned files are preserved. When the call created the output directory and rollback leaves it empty, the publisher removes that directory.

The immutable-real-OKX regression `test_writer_rolls_back_partial_snapshot_commit` covers both first publication and replacement of an existing three-file snapshot. It injects only a metadata replacement failure; it does not alter market observations or produce performance evidence.

This is a recoverable partial-write guarantee, not an atomic three-file generation protocol. Concurrent readers can observe the interval between individual replacements, concurrent writers are not synchronized, and no `fsync` crash-durability guarantee is made. If restoration itself fails, the publisher raises:

```text
OKX snapshot commit failed and rollback was incomplete
```

After that error, the affected destination must be treated as an indeterminate snapshot generation and regenerated before it is used as research evidence.

Executable verification from a checkout with development dependencies installed:

```bash
pytest tests/test_okx_snapshot_integrity.py
```

## Sealed holdout report publication and recovery

`write_research_report()` renders `latest.json` and `latest.md` completely in memory before modifying the destination. It stages both payloads in a temporary directory on the destination filesystem, then publishes JSON first and Markdown second with `os.replace`.

If staging or a later replacement fails, the publisher rolls completed replacements back in reverse order. A failed first publication leaves no partial report files and removes a newly created output directory when it is empty. A failed replacement of an existing valid report restores the prior JSON and Markdown bytes exactly.

If restoration itself fails, the publisher preserves the original commit exception as the cause and raises:

```text
research report commit failed and rollback was incomplete
```

After that error, the destination must be treated as an indeterminate sealed-holdout report generation and regenerated before either file is used as evidence. This is handled-failure recovery, not atomic two-file visibility, concurrent-writer synchronization, or an `fsync` crash-durability guarantee.

The recovery matrix uses the immutable real OKX BTC-USDT `1Dutc` fixture and valid `run_holdout_research()` results. It changes only the transaction-cost configuration for the replacement result so exact prior-byte restoration cannot pass vacuously; it does not generate or alter market observations.

Executable verification:

```bash
pytest tests/test_research_report_failure_recovery.py
```

## Portfolio bundle destination safety

`write_portfolio_risk_bundle()` publishes the final four-file workflow artifact through the shared transactional publisher. Before it creates a staging directory or reads, replaces, or rolls back any destination bytes, the contract requires:

- the final `output_dir` path itself is not a symbolic link;
- every final destination is a unique direct child of that directory;
- none of the four pre-existing destination entries is a symbolic link;
- every staged source is a regular file and a direct child of the private staging directory.

For the canonical CLI, violations fail closed with one of these errors:

```text
portfolio bundle output directory must not be a symbolic link
portfolio bundle destinations must not be symbolic links
```

The regressions preserve the symbolic link, its external target bytes, and unrelated caller-owned files, proving that validation occurs before staging or destination replacement. Use a real output directory containing regular destination files, then regenerate the complete bundle; do not treat files reached through the rejected link as workflow-artifact evidence.

This guard checks the final output-directory entry and final destination entries. It does not reject symbolic links in higher ancestor path components, serialize concurrent path changes, or eliminate a check-to-use race after validation.

Executable verification:

```bash
pytest tests/test_atomic_publish.py tests/test_portfolio_stress_correlation.py
```
