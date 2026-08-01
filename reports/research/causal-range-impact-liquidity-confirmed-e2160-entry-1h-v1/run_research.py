from __future__ import annotations

import argparse
import hashlib
import json
import math
import types
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

FAMILY_ID = "causal-range-impact-liquidity-confirmed-e2160-entry-1h-v1"
VERDICT_REJECT = "reject_causal_range_impact_liquidity_confirmed_e2160_entry_1h_v1"
VERDICT_ACCEPT = "accept_causal_range_impact_liquidity_confirmed_e2160_entry_1h_v1"
SYMBOLS = ("AVAXUSDT", "FILUSDT")
ENGINE_COMMIT = "3419837ab3e598c572458c47906da3bd8b0ed52e"
ENGINE_BLOB_SHA1 = "14e011a2f1eeb0c990cc72649dfa25688dc71ffe"
ENGINE_URL = (
    "https://raw.githubusercontent.com/Dingding-leo/GPT/"
    f"{ENGINE_COMMIT}/reports/research/"
    "causal-price-adjusted-trade-size-confirmed-e2160-entry-1h-v1/run_research.py"
)
ENGINE_PATH = Path("/tmp/range_impact_research_engine.py")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_blob_sha1(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode()
    return hashlib.sha1(header + payload).hexdigest()  # noqa: S324 - Git object identity


def fetch_engine() -> tuple[types.ModuleType, bytes]:
    request = urllib.request.Request(
        ENGINE_URL,
        headers={"User-Agent": "gpt-quant-lab-public-research/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} for immutable engine")
        payload = response.read()
    actual_blob = git_blob_sha1(payload)
    if actual_blob != ENGINE_BLOB_SHA1:
        raise ValueError(f"immutable engine blob mismatch: {actual_blob}")

    source = payload.decode("utf-8")
    old = (
        "data_by_symbol.get(symbol, MarketData(symbol, np.array([]), np.array([]), "
        "np.array([]), np.array([]), np.array([]), np.array([]), np.array([]), "
        "np.array([]), [])).source_objects"
    )
    new = "(data_by_symbol[symbol].source_objects if symbol in data_by_symbol else [])"
    if source.count(old) != 1:
        raise ValueError("base-engine correctness repair identity failed")
    corrected = source.replace(old, new)
    ENGINE_PATH.write_text(corrected)

    module = types.ModuleType("range_impact_engine")
    module.__file__ = str(ENGINE_PATH)
    exec(compile(corrected, str(ENGINE_PATH), "exec"), module.__dict__)
    return module, corrected.encode()


def install_range_impact_architecture(module: types.ModuleType) -> None:
    module.FAMILY_ID = FAMILY_ID
    module.VERDICT_REJECT = VERDICT_REJECT
    module.VERDICT_ACCEPT = VERDICT_ACCEPT
    module.SYMBOLS = SYMBOLS
    original_acquire = module.acquire_market

    def acquire_market(symbol: str) -> Any:
        data = original_acquire(symbol)
        impact = np.full(module.EXPECTED_ROWS, np.nan, dtype=np.float64)
        valid = (data.trades > 0) & (data.highs >= data.lows) & (data.lows > 0)
        impact[valid] = np.log(data.highs[valid] / data.lows[valid]) / np.sqrt(
            data.trades[valid]
        )
        return module.MarketData(
            symbol=data.symbol,
            timestamps_ms=data.timestamps_ms,
            opens=data.opens,
            highs=data.highs,
            lows=data.lows,
            closes=data.closes,
            base_volume=data.base_volume,
            quote_volume=data.quote_volume,
            trades=data.trades,
            size=impact,
            source_objects=data.source_objects,
        )

    def feature_at(data: Any, t: int) -> tuple[float, float] | None:
        if t - 2161 < 0 or t - 1464 < 0:
            return None
        old = data.size[t - 1464 : t - 744]
        recent = data.size[t - 744 : t - 24]
        if (
            len(old) != 720
            or len(recent) != 720
            or not np.isfinite(old).all()
            or not np.isfinite(recent).all()
        ):
            return None
        spot_margin = math.log(data.closes[t - 1] / data.closes[t - 2161])
        liquidity_margin = float(np.median(old) - np.median(recent))
        if not math.isfinite(spot_margin) or not math.isfinite(liquidity_margin):
            return None
        return spot_margin, liquidity_margin

    module.acquire_market = acquire_market
    module.feature_at = feature_at


def rename_feature_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key.replace("size_margin", "liquidity_margin"): rename_feature_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [rename_feature_keys(item) for item in value]
    return value


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Range-impact liquidity-confirmed E2160 entry — terminal evidence",
        "",
        f"- Family: `{result['family_id']}`",
        f"- Markets: `{', '.join(result['protocol']['markets'])}` independently",
        f"- Bar: `{result['bar']}`",
        f"- Fee: exactly `{result['canonical_fee_bps_one_way']}` bps one way",
        f"- Source objects: `{result['source_contract']['verified_objects']}/{result['source_contract']['expected_objects']}`",
        f"- Performance accessed: `{result['performance_accessed']}`",
        f"- Markets passing all gates: `{result['markets_passing_all_gates']}/2`",
        f"- Verdict: `{result['verdict']}`",
        "",
        "## Frozen signal",
        "",
        "`range_impact_h = log(high_h / low_h) / sqrt(number_of_trades_h)`",
        "",
        "At each daily decision, the candidate permits a positive E2160 entry only when the median range impact in the recent lagged 720H block is below the preceding lagged 720H block. E2160 retains sole exit authority.",
        "",
        "## Training-only information support",
        "",
        "| Market | Valid decisions | IQR | Distinct margins | Vetoes | Veto quarters | Deferred entries | Passed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        support = market["support"]
        if support is None:
            lines.append(f"| {market['symbol']} | null | null | null | null | null | null | false |")
            continue
        lines.append(
            f"| {market['symbol']} | {support['valid_training_decisions']} | "
            f"{support['liquidity_margin_iqr']} | "
            f"{support['liquidity_margin_distinct_count']} | "
            f"{support['veto_count']} | {len(support['veto_quarter_counts'])} | "
            f"{support['later_authorized_entry_count']} | {support['passed']} |"
        )

    if result["performance_accessed"]:
        lines.extend(
            [
                "",
                "## Train, OOS and full economics",
                "",
                "| Market | Segment | Strategy | Net return | Sharpe | Max drawdown | Turnover | Fees | Edge/turnover (bp) |",
                "|---|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for market in result["markets"]:
            performance = market["performance"]
            for segment in ("training", "oos", "full"):
                for strategy in ("candidate", "e2160", "always_long"):
                    metrics = performance["segments"][segment][strategy]
                    lines.append(
                        f"| {market['symbol']} | {segment} | {strategy} | "
                        f"{metrics['net_compound_return']:+.6%} | {metrics['sharpe']} | "
                        f"{metrics['maximum_drawdown']:+.6%} | "
                        f"{metrics['one_way_turnover']} | {metrics['modeled_fees']:+.6%} | "
                        f"{metrics['edge_per_turnover_bps']} |"
                    )
            interval = performance["bootstrap"]
            lines.extend(
                [
                    "",
                    f"### {market['symbol']} breadth and uncertainty",
                    "",
                    f"- Positive candidate folds: `{sum(row['candidate_net_return'] > 0 for row in performance['folds'])}/6`",
                    f"- Positive relative folds: `{sum(row['relative_effect'] > 0 for row in performance['folds'])}/6`",
                    f"- Positive-effect concentration: `{performance['positive_relative_fold_concentration']}`",
                    f"- Mean hourly net-difference 95% CI: `{interval['mean_hourly_net_difference_95ci']}`",
                    f"- Annualised Sharpe-difference 95% CI: `{interval['annualized_sharpe_difference_95ci']}`",
                    f"- One-hour-delay candidate: `{performance['one_hour_delay']['candidate']['net_compound_return']:+.6%}`, Sharpe `{performance['one_hour_delay']['candidate']['sharpe']}`",
                    f"- One-hour-delay E2160: `{performance['one_hour_delay']['e2160']['net_compound_return']:+.6%}`, Sharpe `{performance['one_hour_delay']['e2160']['sharpe']}`",
                ]
            )
    else:
        lines.extend(
            [
                "",
                "## Performance disposition",
                "",
                "Training, sealed OOS and full return, Sharpe, drawdown, turnover, benchmark, fold, year, uncertainty and delay metrics are null rather than zero because the preregistered source/support gate did not authorise performance access.",
            ]
        )

    lines.extend(
        [
            "",
            "## Disposition",
            "",
            result["highest_value_discrepancy"],
            "",
            "```json",
            json.dumps(result["machine_readable_verdict"], sort_keys=True, indent=2),
            "```",
            "",
            f"Next strategy-facing action: {result['next_strategy_action']}.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines))


def run(output_dir: Path) -> dict[str, Any]:
    module, corrected_engine = fetch_engine()
    install_range_impact_architecture(module)
    result = rename_feature_keys(module.run(output_dir))
    result["protocol"]["feature"] = (
        "24H-lagged adjacent 720H medians of log(high/low)/sqrt(number_of_trades); "
        "liquidity margin = old median - recent median"
    )
    result["highest_value_discrepancy"] = result["highest_value_discrepancy"].replace(
        "price-adjusted trade-size", "range-impact liquidity"
    )
    wrapper_bytes = Path(__file__).read_bytes()
    result["hashes"]["script_sha256"] = sha256_bytes(wrapper_bytes)
    result["hashes"]["immutable_base_engine_git_blob_sha1"] = ENGINE_BLOB_SHA1
    result["hashes"]["corrected_base_engine_sha256"] = sha256_bytes(corrected_engine)
    result["hashes"]["strategy_code_bundle_sha256"] = sha256_bytes(
        wrapper_bytes + b"\n---IMMUTABLE-ENGINE---\n" + corrected_engine
    )
    result["hashes"]["protocol_sha256"] = sha256_bytes(
        json.dumps(result["protocol"], sort_keys=True).encode()
    )
    result["implementation_provenance"] = {
        "immutable_base_engine_commit": ENGINE_COMMIT,
        "immutable_base_engine_git_blob_sha1": ENGINE_BLOB_SHA1,
        "base_engine_download_credentials": False,
        "architecture_override": "range-impact feature and frozen AVAX/FIL constants only",
    }
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evidence.json").write_bytes(payload)
    (output_dir / "evidence.sha256").write_text(sha256_bytes(payload) + "\n")
    write_report(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
