# Reproducing research results with real exchange data

This repository is real-market-data only. Synthetic, generated, simulated, or fabricated price and volume series are forbidden in research, backtests, examples, CI smoke tests, and unit-test price fixtures. A successful command proves only that the documented software path executed on the identified snapshot; it does not prove a tradable edge.

## Requirements

- Python 3.11 or newer;
- a clean checkout of this repository;
- network access to the public OKX market-data API, or an existing immutable OKX snapshot with matching raw responses and metadata;
- no API key, account credentials, or trading permissions.

## 1. Create the environment

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On Windows PowerShell, activate with:

```powershell
.venv\Scripts\Activate.ps1
```

The package requires Python `>=3.11`; development dependencies provide `pytest` and `ruff`.

## 2. Run static repository checks

```bash
ruff check .
ruff format --check .
```

Do not use a green formatting result as research evidence. It proves only that the source matches the configured Ruff rules.

The current repository still contains legacy tests and a workflow step that generate artificial prices. Until those paths are removed, the full `pytest` suite and the legacy synthetic smoke-test step are policy-blocked and must not be cited as valid evidence.

## 3. Download and test real OKX history

Run the public, unauthenticated OKX walk-forward experiment for BTC:

```bash
python scripts/run_okx_research.py \
  --inst-id BTC-USDT \
  --bar 1Dutc \
  --start 2018-01-01 \
  --base-url https://www.okx.com \
  --output-dir reports/okx/BTC-USDT
```

Repeat independently for ETH:

```bash
python scripts/run_okx_research.py \
  --inst-id ETH-USDT \
  --bar 1Dutc \
  --start 2018-01-01 \
  --base-url https://www.okx.com \
  --output-dir reports/okx/ETH-USDT
```

The script calls `GET /api/v5/market/history-candles`, excludes the current unconfirmed candle, writes the raw paginated responses, and computes rolling out-of-sample results from the normalized close series. The default configuration is `config/okx_research.json`.

Expected files for `BTC-USDT` and `1Dutc` are:

```text
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.raw.json
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json
reports/okx/BTC-USDT/walk_forward.json
reports/okx/BTC-USDT/walk_forward.md
reports/okx/BTC-USDT/walk_forward_returns.csv
```

The command prints `okx_base_url`, `instrument_id`, `bar`, `observations`, `data_sha256`, `walk_forward_folds`, `aggregate_sharpe`, `aggregate_max_drawdown`, `robustness_status`, and every output path.

## 4. CLI options and precedence

Inspect the real-data command directly:

```bash
python scripts/run_okx_research.py --help
```

`run_okx_research.py` supports:

- `--config` — configuration file, default `config/okx_research.json`;
- `--inst-id` — OKX instrument identifier;
- `--bar` — candle interval such as `1Dutc`;
- `--base-url` — OKX API origin;
- `--start` and `--end` — inclusive UTC date/time bounds;
- `--max-pages` — maximum backward-pagination pages;
- `--output-dir` — report and snapshot directory.

For the API origin, precedence is:

1. `--base-url`;
2. environment variable `OKX_BASE_URL`;
3. `data.base_url` in the selected configuration;
4. built-in fallback `https://www.okx.com`.

If a requested `start` boundary cannot be reached before `max_pages` is exhausted, the run must fail rather than silently treat truncated history as complete. A bounded latest-window download without `start` is not evidence of full historical coverage.

## 5. Audit the downloaded snapshot

The metadata file records provider, endpoint, request bounds, retrieval time, row counts, first and last timestamps, missing-interval estimate, and SHA-256 hashes for the normalized CSV and raw paginated responses.

Save the following helper as `verify_snapshot.py`, then run `python verify_snapshot.py`. The helper is portable across macOS, Linux, and Windows PowerShell:

```python
import hashlib
import json
from pathlib import Path

root = Path("reports/okx/BTC-USDT/snapshot")
stem = "okx-BTC-USDT-1Dutc"
metadata = json.loads((root / f"{stem}.metadata.json").read_text(encoding="utf-8"))

assert metadata["provider"] == "OKX"
assert metadata["instrument_id"] == "BTC-USDT"
assert metadata["bar"] == "1Dutc"

for filename, key in [
    (f"{stem}.csv", "normalized_csv_sha256"),
    (f"{stem}.raw.json", "raw_pages_sha256"),
]:
    digest = hashlib.sha256((root / filename).read_bytes()).hexdigest()
    expected = metadata[key]
    if digest != expected:
        raise SystemExit(f"hash mismatch for {filename}: {digest} != {expected}")
    print(f"verified {filename}: {digest}")
```

A hash mismatch means the snapshot bytes no longer match the recorded provenance. Stop; do not run or publish metrics from that snapshot.

Also inspect the metadata fields before using the data:

- `provider`, `endpoint`, `base_url`;
- `instrument_id`, `bar`;
- `requested_start`, `requested_end`;
- `observations`, `start`, `end`;
- `duplicates_removed`, `incomplete_rows_removed`, `missing_intervals`;
- `normalized_csv_sha256`, `raw_pages_sha256`.

## 6. Run the sealed validation/holdout path on the verified snapshot

`run_research.py` currently has a legacy no-`--csv` branch that generates artificial prices. That branch is prohibited. Always pass the normalized CSV produced and verified above:

```bash
python scripts/run_research.py \
  --csv reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv \
  --timestamp-col timestamp \
  --close-col close \
  --output-dir reports/holdout/BTC-USDT
```

Expected files:

```text
reports/holdout/BTC-USDT/latest.json
reports/holdout/BTC-USDT/latest.md
```

This command uses the validation/holdout pipeline rather than the rolling OKX walk-forward experiment. The output is admissible only while the CSV, raw response, and metadata hashes remain linked and verified.

Do not substitute an arbitrary local CSV. A dataset without provider, instrument, timeframe, timestamps, raw-response provenance, request details, and matching SHA-256 metadata is not an accepted research input.

## 7. CI evidence requirements

A GitHub Actions run is valid only when all of the following are true on the exact head commit:

1. Ruff lint and format checks pass;
2. every price/volume test fixture is an immutable, versioned real-exchange extract with provenance;
3. the smoke test uses verified real exchange data, not a generator;
4. BTC-USDT and ETH-USDT real-data research completes;
5. reports, raw responses, normalized snapshots, metadata, and hashes are uploaded;
6. no required step is skipped.

The current workflow's legacy `Run synthetic sealed-holdout smoke test` step is non-compliant. Runs containing that step must not be cited as satisfying the project gate, even when GitHub shows a green conclusion.

## Troubleshooting

### OKX request fails after retries

Confirm that the public API origin is reachable in your region, then override it with `OKX_BASE_URL` or `--base-url`. Do not add API keys; this workflow uses public market data only.

### The requested interval is empty or truncated

Check the instrument, interval, date bounds, and whether `--max-pages` reaches the requested `start`. A downloader must fail if it cannot reach a requested historical boundary; increasing `max_pages` is acceptable, silently accepting partial history is not.

### Results differ between runs

Compare:

1. exact Git commit SHA;
2. configuration file contents;
3. normalized and raw snapshot hashes;
4. instrument, bar, date bounds, API origin, and retrieval timestamp;
5. dependency versions.

OKX may revise exchange-provided historical data. A changed snapshot hash is a data change, not automatically a code regression.

### A test needs malformed input

Start from a copied, hashed real-data fixture and alter only the field or structure needed to prove fail-closed behavior. Do not calculate or publish performance metrics from the altered copy.

## Evidence boundaries

- Historical candle output remains exchange-specific and can be revised.
- Close-price backtests do not model order-book depth, guaranteed fills, or deployment latency.
- A positive holdout or walk-forward result is necessary but insufficient evidence of a deployable strategy.
- Statistical resampling may resample observed real returns only; it must be labelled as resampling and must not create artificial price paths.
- This repository contains no live-order workflow and must not be given trading credentials.
