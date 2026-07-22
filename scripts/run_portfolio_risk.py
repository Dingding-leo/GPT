#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from gpt_quant import (
    build_buy_and_hold_sleeve_portfolio,
    load_verified_return_csv,
    write_portfolio_risk_report,
)
from gpt_quant.portfolio import validate_portfolio_provenance

_HEX_DIGITS = frozenset("0123456789abcdef")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
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
        description="Build a non-optimized BTC/ETH two-sleeve portfolio risk report."
    )
    parser.add_argument("--btc-returns", required=True)
    parser.add_argument("--eth-returns", required=True)
    parser.add_argument("--btc-sha256", required=True, type=_sha256)
    parser.add_argument("--eth-sha256", required=True, type=_sha256)
    parser.add_argument("--btc-weight", type=float, default=0.5)
    parser.add_argument("--eth-weight", type=float, default=0.5)
    parser.add_argument("--max-sleeve-weight", type=float, default=0.75)
    parser.add_argument("--max-variance-contribution", type=float, default=0.75)
    parser.add_argument("--max-pairwise-correlation", type=float, default=0.90)
    parser.add_argument("--annualization", type=int, default=365)
    parser.add_argument("--provider", required=True, choices=("OKX",))
    parser.add_argument("--market-type", required=True, choices=("spot",))
    parser.add_argument("--timeframe", required=True, choices=("1Dutc",))
    parser.add_argument("--source-workflow-run", required=True, type=_positive_int)
    parser.add_argument("--source-artifact-id", required=True, type=_positive_int)
    parser.add_argument("--source-artifact-name", required=True)
    parser.add_argument("--source-artifact-sha256", required=True, type=_sha256)
    parser.add_argument("--source-head-sha", required=True, type=_git_commit)
    parser.add_argument("--output-dir", default="reports/portfolio")
    parser.add_argument(
        "--fail-on-reject",
        action="store_true",
        help="return a non-zero exit status after persisting a rejected risk report",
    )
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
    btc_path = Path(args.btc_returns)
    eth_path = Path(args.eth_returns)
    btc = load_verified_return_csv(btc_path, expected_sha256=args.btc_sha256)
    eth = load_verified_return_csv(eth_path, expected_sha256=args.eth_sha256)
    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": args.btc_weight, "ETH-USDT": args.eth_weight},
        annualization=args.annualization,
        max_sleeve_weight=args.max_sleeve_weight,
        max_variance_contribution=args.max_variance_contribution,
        max_pairwise_correlation=args.max_pairwise_correlation,
        provenance=provenance,
    )
    paths = write_portfolio_risk_report(result, args.output_dir)
    risk_gate_passes = bool(result.concentration["passes"])
    print(f"risk_status={result.risk_status}")
    print(f"risk_gate_passes={str(risk_gate_passes).lower()}")
    print(f"observations={result.data_summary['observations']}")
    print(f"portfolio_total_return={result.portfolio_metrics['total_return']:.6f}")
    print(f"portfolio_sharpe={result.portfolio_metrics['sharpe']:.6f}")
    print(f"portfolio_max_drawdown={result.portfolio_metrics['max_drawdown']:.6f}")
    for name, path in paths.items():
        print(f"{name}_path={path}")
    return 1 if args.fail_on_reject and not risk_gate_passes else 0


if __name__ == "__main__":
    raise SystemExit(main())
