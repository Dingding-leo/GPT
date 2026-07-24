from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_okx_1h_coverage.py"


def _load_coverage_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_okx_1h_coverage_security_test", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load run_okx_1h_coverage.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_coverage_command_rejects_untrusted_origin_before_server_time_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_coverage_script()

    def unexpected_server_time_request(**kwargs: object) -> object:
        pytest.fail(f"untrusted base URL reached server-time transport: {kwargs=}")

    monkeypatch.setattr(
        module,
        "sample_okx_server_time_with_response",
        unexpected_server_time_request,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SCRIPT_PATH),
            "--base-url",
            "http://127.0.0.1:8080",
            "--output-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(ValueError, match="trusted public OKX HTTPS origin"):
        module.main()
