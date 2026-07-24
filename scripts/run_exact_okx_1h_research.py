#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd

from gpt_quant.intraday_1h_source_provenance import write_intraday_1h_source_provenance
from gpt_quant.okx_1h import fetch_okx_one_hour_candles
from gpt_quant.okx_live_response_evidence import sample_okx_server_time_with_response

_SCRIPT_PATH = Path(__file__).with_name("run_okx_research.py")


def _load_research_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("canonical_run_okx_research", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load canonical research runner from {_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("research configuration must contain a JSON object")
    return value


def _hour_timestamp(value: object, *, field: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a valid timestamp") from exc
    if pd.isna(timestamp):
        raise ValueError(f"{field} must be a valid timestamp")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    if timestamp != timestamp.floor("h"):
        raise ValueError(f"{field} must align to an exact UTC hour")
    return timestamp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Acquire exact public OKX 1H bytes, replay them, then run canonical research."
    )
    parser.add_argument("--config", default="config/okx_research_1h.json")
    parser.add_argument("--inst-id", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--manifest-path", required=True)
    return parser.parse_args()


def _completed_end(*, base_url: str, timeout: float, explicit_end: object) -> pd.Timestamp:
    if explicit_end is not None:
        return _hour_timestamp(explicit_end, field="end")
    observation = sample_okx_server_time_with_response(base_url=base_url, timeout=timeout)
    exchange_time = pd.Timestamp(observation.sample.server_time_utc).tz_convert("UTC")
    return exchange_time.floor("h") - pd.Timedelta(hours=1)


def _payload_pages(raw_pages: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    payloads: list[dict[str, Any]] = []
    for index, page in enumerate(raw_pages):
        if not isinstance(page, dict) or set(page) != {
            "payload",
            "raw_response_base64",
            "raw_response_sha256",
        }:
            raise ValueError(f"exact OKX 1H source page {index} has an invalid evidence envelope")
        payload = page["payload"]
        if not isinstance(payload, dict):
            raise ValueError(f"exact OKX 1H source page {index} payload must be a JSON object")
        payloads.append(payload)
    return tuple(payloads)


def main() -> int:
    args = parse_args()
    experiment = _load_json(args.config)
    data = experiment.get("data")
    if not isinstance(data, dict) or str(data.get("bar")) != "1H":
        raise ValueError("exact intraday research requires a 1H data configuration")

    base_url = args.base_url or os.environ.get("OKX_BASE_URL") or str(data["base_url"])
    start = _hour_timestamp(args.start or data.get("start"), field="start")
    limit = int(data.get("limit", 100))
    pause_seconds = float(data.get("pause_seconds", 0.12))
    timeout = float(data.get("timeout", 20.0))
    end = _completed_end(base_url=base_url, timeout=timeout, explicit_end=args.end or data.get("end"))
    if end < start:
        raise ValueError("completed OKX 1H end precedes the configured start")

    snapshot = fetch_okx_one_hour_candles(
        inst_id=args.inst_id,
        start=start,
        end=end,
        base_url=base_url,
        limit=limit,
        pause_seconds=pause_seconds,
        timeout=timeout,
    )
    runner = _load_research_runner()
    original_page_validator = runner._validate_okx_raw_page_schema
    runner.parse_args = lambda: argparse.Namespace(
        config=args.config,
        inst_id=args.inst_id,
        bar="1H",
        base_url=base_url,
        start=start.isoformat(),
        end=end.isoformat(),
        max_pages=int(snapshot.metadata["max_pages"]),
        output_dir=args.output_dir,
        manifest_path=args.manifest_path,
    )
    runner.fetch_okx_history_candles = lambda **kwargs: snapshot
    runner._validate_okx_raw_page_schema = lambda pages: original_page_validator(
        _payload_pages(pages)
    )
    result = int(runner.main())
    if result != 0:
        return result

    path, digest = write_intraday_1h_source_provenance(
        args.output_dir,
        inst_id=args.inst_id,
    )
    print(f"exact_source_provenance_path={path}")
    print(f"exact_source_provenance_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
