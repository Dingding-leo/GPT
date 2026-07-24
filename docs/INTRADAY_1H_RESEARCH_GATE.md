# Canonical 1h research artifact gate

This procedure applies to a checkout that contains the canonical public-OKX `1H`
research workflow and verifiers. Until that implementation reaches `main`, the
default-branch operator path remains the `1Dutc` benchmark. `15m` is not implemented
or approved.

## Scope and safety

The commands use public, read-only OKX spot candles for `BTC-USDT` and `ETH-USDT`.
They do not read credentials, balances, positions, or account state and do not call an
order endpoint.

Canonical modeled economics are exactly **5 bps one-way exchange fee**. Spread,
slippage, market impact, and latency are not added to PnL. Persisted evidence must
label them separately as `not_modeled` or `separate_not_modeled`. A different fee,
an executed profile other than `[1.0]`, or an extra modeled cost path is not canonical
1h evidence.

This is completed-candle, one-bar-delayed close-return research. It does not define a
maker/post-only order, queue priority, no-fill, partial fill, timeout, cancellation,
requote, paper fill, or live fill. Passing the research gate is not paper-trading
acceptance.

## 1. Verify the checkout contract

```bash
python -m pip install -e ".[dev]"
python -m pip check
pytest -q \
  tests/test_intraday_research_profile.py \
  tests/test_verify_intraday_1h_profile.py \
  tests/test_verify_intraday_1h_timestamp_grid.py \
  tests/test_intraday_1h_promotion_gate.py \
  tests/test_intraday_1h_cross_market_gate.py \
  tests/test_artifact_manifest.py \
  tests/test_intraday_1h_research_documentation.py
```

These tests protect public OKX `1H`, annualization `8760`, exactly 5 bps one-way,
`cost_multipliers: [1.0]`, fold-local candidate selection, exact UTC-hour continuity,
a BTC/ETH cross-market gate, portable artifact manifests, and
`persist-credentials: false`.

## 2. Run and recompute one instrument

```bash
python scripts/run_okx_research.py \
  --config config/okx_research_1h.json \
  --inst-id BTC-USDT \
  --output-dir reports/okx/1h/BTC-USDT \
  --manifest-path reports/okx/1h/BTC-USDT/experiment-manifest.jsonl

python scripts/verify_intraday_1h_timestamp_grid.py \
  --output-dir reports/okx/1h/BTC-USDT

python scripts/verify_walk_forward_report.py \
  --output-dir reports/okx/1h/BTC-USDT \
  --manifest-path reports/okx/1h/BTC-USDT/experiment-manifest.jsonl

python scripts/verify_intraday_1h_profile.py \
  --output-dir reports/okx/1h/BTC-USDT

python scripts/build_intraday_1h_promotion_gate.py \
  --output-dir reports/okx/1h/BTC-USDT
```

Repeat with `ETH-USDT`. The timestamp verifier requires duplicate-free metadata,
exact `1H`/3,600-second cadence, UTC-hour alignment, strictly increasing timestamps,
no gaps, `confirm=1` only, matching start/end and observation count, and a CSV SHA-256
matching the metadata. The report verifier recomputes persisted fold selection,
target positions, returns, metrics, and source/config hashes. The profile verifier
fails unless the executed artifacts use only the `1x` 5 bps path.

Read `intraday-promotion-gate.json`. A reproducible artifact may still be rejected for
weak risk-adjusted performance, unstable folds/months/years, tail risk, missing maker
execution, or missing prospective paper evidence.

## 3. Verify portable artifact bytes

Extract each downloaded BTC/ETH artifact into its own empty directory and run from
that directory:

```bash
cd /tmp/canonical-BTC-USDT-1h
sha256sum --check artifact-manifest.sha256
```

Every listed file must report `OK`. This proves that the downloaded artifact tree
matches its root-relative manifest. It does **not** prove that the stored raw-page JSON
contains the exact HTTP response bytes returned by OKX.

## 4. Require exact OKX page bytes before source-provenance acceptance

Run this gate against both extracted market artifacts:

```bash
python - \
  /tmp/canonical-BTC-USDT-1h \
  /tmp/canonical-ETH-USDT-1h <<'PY'
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sys
from pathlib import Path


def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


for root_arg in sys.argv[1:]:
    root = Path(root_arg)
    raw_files = sorted((root / "snapshot").glob("okx-*-1H.raw.json"))
    if len(raw_files) != 1:
        raise ValueError(f"{root}: expected exactly one 1H raw-page bundle")
    raw_path = raw_files[0]
    pages = json.loads(
        raw_path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
    )
    if not isinstance(pages, list) or not pages:
        raise ValueError(f"{raw_path}: raw-page bundle must be a non-empty list")

    required = {"payload", "raw_response_base64", "raw_response_sha256"}
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or set(page) != required:
            raise ValueError(
                f"{raw_path}: page {index} lacks exact provider-byte envelope; "
                "artifact integrity is not exact OKX response provenance"
            )
        encoded = page["raw_response_base64"]
        expected_sha = page["raw_response_sha256"]
        if not isinstance(encoded, str) or not isinstance(expected_sha, str):
            raise ValueError(f"{raw_path}: page {index} byte evidence fields are invalid")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"{raw_path}: page {index} base64 is invalid") from exc
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            raise ValueError(f"{raw_path}: page {index} SHA-256 mismatch")
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
        if decoded != page["payload"]:
            raise ValueError(f"{raw_path}: page {index} payload differs from exact bytes")

    print(f"{raw_path.name}: exact_provider_page_bytes=passed pages={len(pages)}")
PY
```

The currently generated canonical research artifacts are expected to fail this gate:
their `*.raw.json` files store parsed page mappings rather than per-page
`raw_response_base64` and `raw_response_sha256` envelopes. Therefore a portable
manifest can be valid while exact provider-byte provenance is still unavailable.
Do not treat a cross-market field such as `evidence_integrity_passes: true` as
sufficient source-provenance evidence until **both** market artifacts print
`exact_provider_page_bytes=passed`.

Current `main` has a separate exact-byte OKX `1H` coverage boundary. The research
artifact must consume that immutable source artifact, or prove byte/hash equality to
it, rather than treating a second parsed-mapping download as equivalent provenance.

## 5. Keep execution diagnostics separate from PnL

```bash
python - /tmp/canonical-BTC-USDT-1h <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
verification = json.loads(
    (root / "walk_forward_verification.json").read_text(encoding="utf-8")
)
for field in ("spread_model", "slippage_model", "market_impact_model", "latency_model"):
    assert verification[field] == "not_modeled", (field, verification.get(field))
print("execution_diagnostics_separate=passed")
PY
```

This check does not claim zero spread, zero slippage, zero impact, or zero latency. It
proves only that none was silently hidden inside the 5 bps research fee.

## Acceptance boundary

Portable hashes, timestamp continuity, full-reselection recomputation, and the exact
5 bps profile are necessary but not sufficient. Until exact provider page bytes pass
for BTC and ETH, 1h source provenance remains blocked. `15m` evaluation, paper
promotion, and limited-capital deployment remain blocked regardless of green CI or a
valid artifact manifest.

Additional paper/live blockers remain maker lifecycle evidence, instrument-constrained
sizing at order creation, durable cash/order/position state, restart recovery,
reconciliation, idempotency, kill switches, monitoring, and prospective paper
acceptance.
