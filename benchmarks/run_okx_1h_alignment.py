#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

_EXPECTED_SHA256 = {
    "BTC-USDT/snapshot/okx-BTC-USDT-1H.csv": (
        "c48322ba3fc80ee6e2b71b71ecf2c5f04d962fbfe87544f9f5cf84e08f49ccc9"
    ),
    "BTC-USDT/snapshot/okx-BTC-USDT-1H.raw.json": (
        "fcc3543b0d15b8f4c409ed8416399b8559a3fd2035166ca1ca18597177481829"
    ),
    "BTC-USDT/snapshot/okx-BTC-USDT-1H.metadata.json": (
        "a2661c9a81dbc5a35db035e79ecd94eb8e848f18b57fd64a7dc1550b316e246d"
    ),
    "ETH-USDT/snapshot/okx-ETH-USDT-1H.csv": (
        "6fe601b0806fcf86ffd627de8df3db6350b909dff93000487a5a5b783812016d"
    ),
    "ETH-USDT/snapshot/okx-ETH-USDT-1H.raw.json": (
        "0abe6ebd3659b71851b85e033b7ae64961f97c840270fe542de025acb9396abd"
    ),
    "ETH-USDT/snapshot/okx-ETH-USDT-1H.metadata.json": (
        "e42744bca0a0af58f2a2030d75680adc1e82302e7c8855b3c6b3a02c96cb7ad6"
    ),
    "coverage-manifest.json": (
        "faa00e467091d3abf90d2fc5e4df2a516f8c7d256d489fde09ba0f5a67a40013"
    ),
}
_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
_MODES = ("baseline", "optimized")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_inputs(root: Path) -> None:
    for relative, expected in _EXPECTED_SHA256.items():
        actual = _sha256(root / relative)
        if actual != expected:
            raise ValueError(f"benchmark input hash mismatch for {relative}: {actual}")


def _run_worker(args: argparse.Namespace) -> None:
    import gpt_quant.okx_1h as okx_1h_module

    def scalar_exact_hour_check(index) -> bool:
        return all(timestamp == timestamp.floor("h") for timestamp in index)

    if args.mode == "baseline":
        okx_1h_module._is_exact_hour_index = scalar_exact_hour_check

    snapshot_dir = args.artifact_dir / args.instrument / "snapshot"
    started = time.perf_counter()
    snapshot = okx_1h_module.replay_persisted_okx_one_hour_snapshot(
        snapshot_dir,
        inst_id=args.instrument,
    )
    elapsed = time.perf_counter() - started
    identity = hashlib.sha256(
        (
            snapshot._source_normalized_csv_sha256
            + snapshot._source_raw_pages_sha256
            + snapshot._source_metadata_sha256
        ).encode()
    ).hexdigest()
    print(
        json.dumps(
            {
                "elapsed_seconds": elapsed,
                "identity_sha256": identity,
                "instrument": args.instrument,
                "mode": args.mode,
                "observations": len(snapshot.candles),
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            },
            sort_keys=True,
        )
    )


def _invoke_worker(
    *,
    artifact_dir: Path,
    instrument: str,
    mode: str,
) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            __file__,
            "--worker",
            "--artifact-dir",
            str(artifact_dir),
            "--instrument",
            instrument,
            "--mode",
            mode,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _run_benchmark(args: argparse.Namespace) -> None:
    if args.samples <= 0:
        raise ValueError("samples must be positive")
    _verify_inputs(args.artifact_dir)

    elapsed = {mode: [] for mode in _MODES}
    peak_rss = {mode: [] for mode in _MODES}
    identities: dict[str, str] = {}
    observations: dict[str, int] = {}

    for sample in range(args.samples):
        modes = _MODES if sample % 2 == 0 else tuple(reversed(_MODES))
        for mode in modes:
            instruments = _INSTRUMENTS if sample % 2 == 0 else tuple(reversed(_INSTRUMENTS))
            for instrument in instruments:
                result = _invoke_worker(
                    artifact_dir=args.artifact_dir,
                    instrument=instrument,
                    mode=mode,
                )
                elapsed[mode].append(float(result["elapsed_seconds"]))
                peak_rss[mode].append(int(result["peak_rss_kib"]))
                identity = str(result["identity_sha256"])
                prior_identity = identities.setdefault(instrument, identity)
                if prior_identity != identity:
                    raise AssertionError(f"replay identity drift for {instrument}")
                rows = int(result["observations"])
                prior_rows = observations.setdefault(instrument, rows)
                if prior_rows != rows:
                    raise AssertionError(f"replay observation drift for {instrument}")

    baseline = statistics.median(elapsed["baseline"])
    optimized = statistics.median(elapsed["optimized"])
    baseline_peak = max(peak_rss["baseline"])
    optimized_peak = max(peak_rss["optimized"])
    print(
        json.dumps(
            {
                "baseline_median_seconds": baseline,
                "baseline_peak_rss_kib": baseline_peak,
                "equivalence": "exact_verified_snapshot_identity_and_observation_count",
                "identity_sha256": identities,
                "input_sha256": _EXPECTED_SHA256,
                "observations": observations,
                "optimized_median_seconds": optimized,
                "optimized_peak_rss_kib": optimized_peak,
                "peak_rss_change_fraction": optimized_peak / baseline_peak - 1.0,
                "runtime_reduction_fraction": 1.0 - optimized / baseline,
                "samples_per_mode_instrument": args.samples,
                "speedup": baseline / optimized,
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--samples", default=3, type=int)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--instrument", choices=_INSTRUMENTS)
    parser.add_argument("--mode", choices=_MODES)
    args = parser.parse_args()
    if args.worker:
        if args.instrument is None or args.mode is None:
            parser.error("--worker requires --instrument and --mode")
        _run_worker(args)
    else:
        _run_benchmark(args)


if __name__ == "__main__":
    main()
