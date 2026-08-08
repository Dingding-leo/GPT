from __future__ import annotations

import json

import numpy as np

import run_okb_risk_appetite as base

SOURCE_SAFETY_PAGES = 64


def _fetch_with_frozen_page_allowance(inst_id: str, *, end: str) -> object:
    return base.fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=base.START,
        end=end,
        limit=100,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=SOURCE_SAFETY_PAGES,
    )


def _json_scalar_safe(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: _json_scalar_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_scalar_safe(item) for item in value]
    return value


def _write_result_with_json_scalar_normalization(report: dict[str, object]) -> str:
    normalized = _json_scalar_safe(report)
    base.OUTPUT.mkdir(parents=True, exist_ok=True)
    result_path = base.OUTPUT / "result-summary.json"
    data = (
        json.dumps(normalized, indent=2, sort_keys=True, allow_nan=True) + "\n"
    ).encode()
    result_path.write_bytes(data)
    digest = base._sha256(data)
    print(json.dumps(normalized, indent=2, sort_keys=True, allow_nan=True))
    print(f"result_sha256={digest}")
    return digest


def main() -> int:
    base._fetch = _fetch_with_frozen_page_allowance
    base._write_result = _write_result_with_json_scalar_normalization
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
