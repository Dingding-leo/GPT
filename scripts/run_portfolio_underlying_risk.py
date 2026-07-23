#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from collections.abc import Sequence
from pathlib import Path

from gpt_quant.portfolio import validate_portfolio_provenance
from gpt_quant.portfolio_path_risk_budget import (
    evaluate_portfolio_path_risk_budget,
    write_portfolio_path_risk_budget_report,
)
from gpt_quant.portfolio_underlying_risk import (
    build_underlying_sleeve_risk,
    write_underlying_sleeve_risk_report,
)

_HEX_DIGITS = frozenset("0123456789abcdef")
_EXCHANGE_FEE_BASELINE_BPS = 5.0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise argparse.ArgumentTypeError("value must be a positive finite number")
    return parsed


def _drawdown_floor(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not -1.0 < parsed < 0.0:
        raise argparse.ArgumentTypeError("value must be a finite number in (-1, 0)")
    return parsed


def _hex_digest(value: str, *, lengths: set[int], label: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) not in lengths or not set(normalized) <= _HEX_DIGITS:
        expected = " or ".join(str(length) for length in sorted(lengths))
        raise argparse.ArgumentTypeError(
            f"{label} must be a {expected}-character hexadecimal digest"
        )
    return normalized


def _sha256(value: str) -> str:
    return _hex_digest(value, lengths={64}, label="SHA-256")


def _git_commit(value: str) -> str:
    return _hex_digest(value, lengths={40, 64}, label="source head SHA")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Expose source-bound underlying sleeve risk and enforce explicit portfolio "
            "volatility and drawdown budgets."
        )
    )
    parser.add_argument("--btc-returns", required=True)
    parser.add_argument("--eth-returns", required=True)
    parser.add_argument("--btc-sha256", required=True, type=_sha256)
    parser.add_argument("--eth-sha256", required=True, type=_sha256)
    parser.add_argument("--btc-weight", type=float, default=0.5)
    parser.add_argument("--eth-weight", type=float, default=0.5)
    parser.add_argument("--annualization", type=int, default=365)
    parser.add_argument(
        "--max-annualized-net-volatility",
        required=True,
        type=_positive_float,
    )
    parser.add_argument(
        "--maximum-drawdown-floor",
        required=True,
        type=_drawdown_floor,
    )
    parser.add_argument("--fail-on-reject", action="store_true")
    parser.add_argument("--provider", required=True, choices=("OKX",))
    parser.add_argument("--market-type", required=True, choices=("spot",))
    parser.add_argument("--timeframe", required=True, choices=("1Dutc",))
    parser.add_argument("--source-workflow-run", required=True, type=_positive_int)
    parser.add_argument("--source-artifact-id", required=True, type=_positive_int)
    parser.add_argument("--source-artifact-name", required=True)
    parser.add_argument("--source-artifact-sha256", required=True, type=_sha256)
    parser.add_argument("--source-head-sha", required=True, type=_git_commit)
    parser.add_argument("--output-dir", default="reports/portfolio")
    return parser.parse_args(argv)


def _validated_provenance(args: argparse.Namespace) -> dict[str, object]:
    if args.btc_sha256 == args.eth_sha256:
        raise ValueError("BTC-USDT and ETH-USDT return files must have distinct SHA-256 digests")
    return validate_portfolio_provenance(
        {
            "provider": args.provider,
            "market_type": args.market_type,
            "timeframe": args.timeframe,
            "source_workflow_run_id": args.source_workflow_run,
            "source_artifact_id": args.source_artifact_id,
            "source_artifact_name": args.source_artifact_name,
            "source_artifact_sha256": args.source_artifact_sha256,
            "source_head_sha": args.source_head_sha,
            "return_file_sha256": {
                "BTC-USDT": args.btc_sha256,
                "ETH-USDT": args.eth_sha256,
            },
        },
        expected_sleeves=("BTC-USDT", "ETH-USDT"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    provenance = _validated_provenance(args)
    result = build_underlying_sleeve_risk(
        {
            "BTC-USDT": Path(args.btc_returns),
            "ETH-USDT": Path(args.eth_returns),
        },
        expected_sha256={
            "BTC-USDT": args.btc_sha256,
            "ETH-USDT": args.eth_sha256,
        },
        initial_weights={
            "BTC-USDT": args.btc_weight,
            "ETH-USDT": args.eth_weight,
        },
        provenance=provenance,
        annualization=args.annualization,
        exchange_fee_bps=_EXCHANGE_FEE_BASELINE_BPS,
    )
    underlying_path = write_underlying_sleeve_risk_report(result, args.output_dir)
    budget = evaluate_portfolio_path_risk_budget(
        result,
        max_annualized_net_volatility=args.max_annualized_net_volatility,
        maximum_drawdown_floor=args.maximum_drawdown_floor,
    )
    budget_path = write_portfolio_path_risk_budget_report(budget, args.output_dir)

    print(f"underlying_risk_path={underlying_path}")
    print(f"portfolio_path_risk_budget_path={budget_path}")
    print(
        "current_absolute_market_exposure="
        f"{result.portfolio_metrics['current_absolute_market_exposure']:.6f}"
    )
    print(
        "annualized_weighted_underlying_turnover="
        f"{result.portfolio_metrics['annualized_weighted_underlying_turnover']:.6f}"
    )
    print(
        f"portfolio_exchange_fee_sum={result.portfolio_metrics['portfolio_exchange_fee_sum']:.6f}"
    )
    print(f"annualized_net_volatility={budget.metrics['annualized_net_volatility']:.6f}")
    print(f"maximum_drawdown={budget.metrics['maximum_drawdown']:.6f}")
    print(f"portfolio_path_risk_budget_status={budget.payload['risk_budget']['status']}")
    if args.fail_on_reject and not budget.passes:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
