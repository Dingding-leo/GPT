# Portable canonical 1h research artifact gate

This procedure applies to a checkout containing `config/okx_research_1h.json`,
`.github/workflows/intraday-1h-research.yml`, and
`scripts/verify_intraday_1h_profile.py`. Until that implementation reaches `main`, the
default-branch operator path remains the `1Dutc` benchmark. `15m` is not implemented
or approved.

## Scope and safety

The commands use public, read-only OKX spot candles for `BTC-USDT` or `ETH-USDT`.
They do not read credentials, balances, positions, or account state and do not call an
order endpoint.

Canonical modeled economics are exactly **5 bps one-way exchange fee**. Spread,
slippage, market impact, and latency are not added to PnL; the persisted verification
record must label each one `not_modeled`. A different fee, an executed profile other
than `[1.0]`, or an extra cost path is not canonical 1h evidence.

This is completed-candle, one-bar-delayed close-return research. It does not define a
maker/post-only order, queue priority, no-fill, partial fill, timeout, cancellation,
requote, paper fill, or live fill. Passing this gate is not paper-trading acceptance.

## 1. Verify the checkout

```bash
python -m pip install -e ".[dev]"
python -m pip check
pytest -q \
  tests/test_intraday_research_profile.py \
  tests/test_verify_intraday_1h_profile.py \
  tests/test_intraday_1h_promotion_gate.py \
  tests/test_artifact_manifest.py \
  tests/test_intraday_1h_research_documentation.py
```

The tests require public OKX `1H`, annualization `8760`, exactly 5 bps one-way,
`cost_multipliers: [1.0]`, fold-local candidate selection, a BTC/ETH workflow matrix,
and `persist-credentials: false`.

## 2. Run and recompute one instrument

```bash
python scripts/run_okx_research.py \
  --config config/okx_research_1h.json \
  --inst-id BTC-USDT \
  --output-dir reports/okx/1h/BTC-USDT \
  --manifest-path reports/okx/1h/BTC-USDT/experiment-manifest.jsonl

python scripts/verify_walk_forward_report.py \
  --output-dir reports/okx/1h/BTC-USDT \
  --manifest-path reports/okx/1h/BTC-USDT/experiment-manifest.jsonl
```

Repeat with `ETH-USDT`. The verifier recomputes persisted fold selection, target
positions, returns, metrics, and source/config hashes. Do not promote a report that
cannot be recomputed.

## 3. Require the exact executed 5 bps profile

```bash
python scripts/verify_intraday_1h_profile.py \
  --output-dir reports/okx/1h/BTC-USDT
```

The command fails unless the persisted effective config and report both use `1H`,
`transaction_cost_bps == 5.0`, `cost_multipliers == [1.0]`, at least one candidate,
and a `1x` metric path exactly equal to the selected aggregate path.

## 4. Publish explicit research blockers

```bash
python scripts/build_intraday_1h_promotion_gate.py \
  --output-dir reports/okx/1h/BTC-USDT
```

Read `intraday-promotion-gate.json`. A reproducible artifact may still be rejected for
weak risk-adjusted performance, unstable folds/months/years, inadequate activity,
tail risk, capacity, missing maker execution, or missing prospective paper evidence.

## 5. Verify a downloaded artifact from any directory

Extract the artifact into any empty directory and run the check from that directory:

```bash
cd /tmp/canonical-BTC-USDT-1h
sha256sum --check artifact-manifest.sha256
```

The manifest contains artifact-root-relative paths. Every file must report `OK`; the
operator no longer needs to recreate the original Actions workspace path.

Then rerun the exact profile verifier against the extracted directory:

```bash
python /path/to/GPT/scripts/verify_intraday_1h_profile.py \
  --output-dir /tmp/canonical-BTC-USDT-1h
```

## 6. Keep execution diagnostics separate from PnL

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

Passing all commands proves portable, source-hashed, full-reselection 1h research
charged exactly 5 bps one-way. It does not prove strategy quality or executable fills.
Current paper/live blockers remain maker lifecycle evidence, instrument-constrained
sizing at order creation, durable cash/order/position state, restart recovery,
reconciliation, idempotency, kill switches, monitoring, and prospective paper
acceptance.
