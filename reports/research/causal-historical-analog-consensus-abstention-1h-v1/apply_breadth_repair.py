from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    path = Path(sys.argv[1])
    source = path.read_text()
    start = source.index("def breadth(")
    end = source.index("\n\ndef forecast_diagnostics", start)
    replacement = '''def compounded_return(values: np.ndarray) -> float:
    return float(np.prod(1.0 + values) - 1.0)


def breadth(
    data: MarketData, candidate: PathResult, benchmark: PathResult
) -> dict[str, Any]:
    if (
        len(candidate.net_returns) != OOS_END - OOS_START
        or len(benchmark.net_returns) != OOS_END - OOS_START
    ):
        raise RuntimeError("breadth paths must be the complete OOS paths")

    def effect_slice(start: int, end: int) -> tuple[float, float, float]:
        left, right = start - OOS_START, end - OOS_START
        candidate_return = compounded_return(candidate.net_returns[left:right])
        benchmark_return = compounded_return(benchmark.net_returns[left:right])
        return (
            candidate_return,
            benchmark_return,
            candidate_return - benchmark_return,
        )

    folds: list[dict[str, Any]] = []
    for start in range(OOS_START, OOS_END, FOLD_HOURS):
        end = min(start + FOLD_HOURS, OOS_END)
        candidate_return, benchmark_return, relative_effect = effect_slice(start, end)
        folds.append(
            {
                "start": start,
                "end": end,
                "candidate_net_return": candidate_return,
                "e2160_net_return": benchmark_return,
                "relative_net_effect": relative_effect,
            }
        )
    years_by_hour = np.asarray(
        [
            datetime.fromtimestamp(timestamp / 1000, tz=UTC).year
            for timestamp in data.open_ms[OOS_START:OOS_END]
        ]
    )
    years: list[dict[str, Any]] = []
    for year in sorted(set(int(value) for value in years_by_hour)):
        offsets = np.flatnonzero(years_by_hour == year)
        start = OOS_START + int(offsets[0])
        end = OOS_START + int(offsets[-1]) + 1
        candidate_return, benchmark_return, relative_effect = effect_slice(start, end)
        years.append(
            {
                "year": year,
                "start": start,
                "end": end,
                "candidate_net_return": candidate_return,
                "e2160_net_return": benchmark_return,
                "relative_net_effect": relative_effect,
            }
        )
    positive_effects = [max(0.0, float(item["relative_net_effect"])) for item in folds]
    positive_sum = sum(positive_effects)
    concentration = max(positive_effects, default=0.0) / positive_sum if positive_sum > 0 else 1.0
    return {
        "method": "contiguous slices of isolated continuous OOS paths",
        "folds": folds,
        "years": years,
        "positive_relative_folds": int(sum(item["relative_net_effect"] > 0 for item in folds)),
        "positive_candidate_years": int(sum(item["candidate_net_return"] > 0 for item in years)),
        "positive_relative_years": int(sum(item["relative_net_effect"] > 0 for item in years)),
        "positive_fold_concentration": float(concentration),
    }
'''
    source = source[:start] + replacement + source[end:]
    old_call = 'breadth_result = breadth(data, forecasts["oos"])'
    new_call = 'breadth_result = breadth(data, oos["candidate"], oos["e2160"])'
    if source.count(old_call) != 1:
        raise RuntimeError("unexpected breadth call count")
    source = source.replace(old_call, new_call)
    path.write_text(source)


if __name__ == "__main__":
    main()
