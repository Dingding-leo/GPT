from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_FIXTURE = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc" / "raw.json"


def _load_run_okx_research_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "run_okx_research_data_schema", "scripts/run_okx_research.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load scripts/run_okx_research.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _changed_real_pages() -> list[dict[str, object]]:
    source_pages = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    changed_pages = copy.deepcopy(source_pages)
    changed_pages[0]["data"][0].append("unexpected-provider-field")
    return changed_pages


def test_okx_research_rejects_raw_candle_schema_drift() -> None:
    module = _load_run_okx_research_module()
    source_pages = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    module._validate_okx_raw_page_schema(tuple(source_pages))

    with pytest.raises(ValueError, match=r"page 0 row 0 must contain exactly 9 fields"):
        module._validate_okx_raw_page_schema(tuple(_changed_real_pages()))


def test_okx_research_rejects_schema_drift_before_writing_or_backtesting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_run_okx_research_module()
    args = argparse.Namespace(
        config="unused.json",
        inst_id=None,
        bar=None,
        base_url=None,
        start=None,
        end=None,
        max_pages=None,
        output_dir="unused",
        manifest_path=None,
    )
    monkeypatch.setattr(module, "parse_args", lambda: args)
    monkeypatch.setattr(module, "load_json", lambda _path: {"data": {}})
    monkeypatch.setattr(
        module,
        "fetch_okx_history_candles",
        lambda **_kwargs: SimpleNamespace(raw_pages=tuple(_changed_real_pages())),
    )
    monkeypatch.setattr(
        module,
        "write_okx_snapshot",
        lambda *_args, **_kwargs: pytest.fail("schema drift reached snapshot writing"),
    )
    monkeypatch.setattr(
        module,
        "run_walk_forward_research",
        lambda *_args, **_kwargs: pytest.fail("schema drift reached backtesting"),
    )

    with pytest.raises(ValueError, match=r"page 0 row 0 must contain exactly 9 fields"):
        module.main()
