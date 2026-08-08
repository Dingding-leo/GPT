from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "causal-onchain-transfer-size-breadth-opportunity-1h-v1"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
OOS_END = 23_760
SOURCE_END = 24_144
FEE_ONE_WAY = 0.0005
ROUND_TRIP_FEE = 0.0010
BASELINE_HOURS = 720
RECENT_HOURS = 168
E2160_HOURS = 2_160
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
CM_ROOT = "https://community-api.coinmetrics.io/v4"
OUTPUT = Path("reports/research/onchain-transfer-size-breadth-1h-v1")
TARGETS = {
    "BCH-USDT": ("bch", 2026080815),
    "LTC-USDT": ("ltc", 2026080816),
}
METRICS = ("TxTfrValMeanNtv", "TxTfrValMedNtv")
ACCEPT = (
    "accept_causal_onchain_transfer_size_breadth_information_premise_1h_v1_"
    "for_separate_candidate_predeclaration"
)
REJECT = "reject_causal_onchain_transfer_size_breadth_information_premise_1h_v1"
SOURCE_REJECT = "reject_causal_onchain_transfer_size_breadth_source_contract_1h_v1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _canonical_frame_bytes(frame: pd.DataFrame) -> bytes:
    return frame.reset_index(names="time").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%SZ",
        float_format="%.17g",
        lineterminator="\n",
    ).encode()


def _http_get(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, object], str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "community-api.coinmetrics.io":
        raise ValueError(f"Coin Metrics URL outside frozen Community host: {url}")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if "api_key" in query or "apikey" in query or "token" in query:
        raise ValueError("credential parameter present in Community URL")
    req = urllib.request.Request(url, headers={"User-Agent": "gpt-quant-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        final_url = resp.geturl()
    final = urlparse(final_url)
    if final.scheme != "https" or final.hostname != "community-api.coinmetrics.io":
        raise ValueError(f"Coin Metrics redirect left frozen host: {final_url}")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Coin Metrics response is not a JSON object")
    return raw, payload, final_url


def _catalog_contract(asset: str, source_dir: Path) -> dict[str, object]:
    url = f"{CM_ROOT}/catalog-v2/asset-metrics"
    raw, payload, final_url = _http_get(url)
    (source_dir / f"coinmetrics-{asset}-catalog.json").write_bytes(raw)
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Coin Metrics catalog response missing data list")
    match = next((row for row in data if isinstance(row, dict) and row.get("asset") == asset), None)
    if match is None:
        raise ValueError(f"{asset}: absent from credential-free catalog")
    metric_rows = match.get("metrics")
    if not isinstance(metric_rows, list):
        raise ValueError(f"{asset}: catalog metrics missing")
    available: dict[str, list[str]] = {}
    for row in metric_rows:
        if not isinstance(row, dict):
            continue
        name = row.get("metric")
        frequencies = row.get("frequencies")
        if not isinstance(name, str) or not isinstance(frequencies, list):
            continue
        available[name] = [
            str(item.get("frequency"))
            for item in frequencies
            if isinstance(item, dict) and item.get("frequency") is not None
        ]
    for metric in METRICS:
        if metric not in available or "1h" not in available[metric]:
            raise ValueError(f"{asset}: {metric} 1h not declared by credential-free catalog")
    return {
        "request_url": final_url,
        "response_sha256": _sha(raw),
        "asset": asset,
        "metrics": {metric: available[metric] for metric in METRICS},
        "passed": True,
    }


def _cm_query(asset: str) -> str:
    params = {
        "assets": asset,
        "metrics": ",".join(METRICS),
        "frequency": "1h",
        "start_time": START,
        "end_time": END,
        "page_size": "10000",
        "paging_from": "start",
    }
    return f"{CM_ROOT}/timeseries/asset-metrics?{urllib.parse.urlencode(params)}"


def _fetch_cm_once(
    asset: str,
    source_dir: Path,
    tag: str,
    persist_pages: bool,
) -> tuple[pd.DataFrame, dict[str, object]]:
    url: str | None = _cm_query(asset)
    rows: list[dict[str, object]] = []
    page_meta: list[dict[str, object]] = []
    page_no = 0
    seen_urls: set[str] = set()
    while url:
        if url in seen_urls:
            raise ValueError(f"{asset}: Coin Metrics pagination loop")
        seen_urls.add(url)
        raw, payload, final_url = _http_get(url)
        if persist_pages:
            (source_dir / f"coinmetrics-{asset}-{tag}-page-{page_no:02d}.json").write_bytes(raw)
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError(f"{asset}: Coin Metrics page missing data list")
        rows.extend(row for row in data if isinstance(row, dict))
        page_meta.append(
            {
                "request_url": final_url,
                "sha256": _sha(raw),
                "rows": len(data),
            }
        )
        next_url = payload.get("next_page_url")
        if next_url in (None, ""):
            url = None
        elif isinstance(next_url, str):
            parsed = urlparse(next_url)
            if parsed.scheme != "https" or parsed.hostname != "community-api.coinmetrics.io":
                raise ValueError(f"{asset}: next_page_url left Community host")
            query = parse_qs(parsed.query, keep_blank_values=True)
            if any(key in query for key in ("api_key", "apikey", "token")):
                raise ValueError(f"{asset}: next_page_url contains credential")
            url = next_url
        else:
            raise ValueError(f"{asset}: invalid next_page_url")
        page_no += 1
        time.sleep(0.7)

    if len(rows) != EXPECTED_ROWS:
        raise ValueError(f"{asset}: expected {EXPECTED_ROWS} Coin Metrics rows, got {len(rows)}")
    expected_index = pd.date_range(START, END, freq="h")
    parsed_rows: list[tuple[pd.Timestamp, float, float]] = []
    for row in rows:
        if row.get("asset") != asset:
            raise ValueError(f"{asset}: wrong asset in Coin Metrics row")
        try:
            ts = pd.Timestamp(str(row["time"]))
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            mean = float(row[METRICS[0]])
            median = float(row[METRICS[1]])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{asset}: invalid/null Coin Metrics row") from exc
        if not math.isfinite(mean) or not math.isfinite(median) or mean < 0 or median < 0:
            raise ValueError(f"{asset}: non-finite or negative transfer-size metric")
        parsed_rows.append((ts, mean, median))
    frame = pd.DataFrame(parsed_rows, columns=["time", "mean_ntv", "median_ntv"]).set_index("time")
    frame = frame.sort_index()
    if frame.index.has_duplicates:
        raise ValueError(f"{asset}: duplicate Coin Metrics timestamps")
    if not frame.index.equals(expected_index):
        raise ValueError(f"{asset}: Coin Metrics series does not match exact frozen 1H grid")
    normalized = _canonical_frame_bytes(frame)
    if persist_pages:
        (source_dir / f"coinmetrics-{asset}-1h.csv").write_bytes(normalized)
    return frame, {
        "asset": asset,
        "rows": len(frame),
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "normalized_sha256": _sha(normalized),
        "pages": page_meta,
        "page_count": page_no,
    }


def _acquire_chain(asset: str, source_dir: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    catalog = _catalog_contract(asset, source_dir)
    primary, primary_meta = _fetch_cm_once(asset, source_dir, "primary", True)
    repeat, repeat_meta = _fetch_cm_once(asset, source_dir, "repeat", False)
    if not primary.equals(repeat):
        raise ValueError(f"{asset}: repeated Coin Metrics acquisition differs")
    if primary_meta["normalized_sha256"] != repeat_meta["normalized_sha256"]:
        raise ValueError(f"{asset}: repeated normalized source hash differs")
    return primary, {
        "catalog": catalog,
        "primary": primary_meta,
        "repeat_normalized_sha256": repeat_meta["normalized_sha256"],
        "repeat_identity": True,
        "prefix_sha256": _sha(_canonical_frame_bytes(primary.iloc[:TRAIN_END])),
        "passed": True,
    }


def _acquire_okx(inst: str, source_dir: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    def fetch() -> object:
        return fetch_okx_one_hour_candles(
            inst_id=inst,
            start=START,
            end=END,
            limit=100,
            pause_seconds=0.08,
            timeout=20.0,
            safety_pages=64,
        )

    first = fetch()
    second = fetch()
    frame = first.candles.copy()
    repeat = second.candles.copy()
    frame.columns = [str(c).lower() for c in frame.columns]
    repeat.columns = [str(c).lower() for c in repeat.columns]
    expected_index = pd.date_range(START, END, freq="h")
    if len(frame) != EXPECTED_ROWS or not frame.index.equals(expected_index):
        raise ValueError(f"{inst}: OKX source does not match exact frozen grid")
    if not frame.equals(repeat):
        raise ValueError(f"{inst}: repeated OKX source differs")
    prices = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or not (prices > 0).all():
        raise ValueError(f"{inst}: invalid OHLC")
    if not (frame["high"] >= frame[["open", "close", "low"]].max(axis=1)).all():
        raise ValueError(f"{inst}: invalid high")
    if not (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)).all():
        raise ValueError(f"{inst}: invalid low")
    out = source_dir / f"okx-{inst}-1h.csv"
    raw = _canonical_frame_bytes(frame[["open", "high", "low", "close"]])
    out.write_bytes(raw)
    return frame, {
        "instrument": inst,
        "rows": len(frame),
        "normalized_sha256": _sha(raw),
        "repeat_identity": True,
        "metadata_normalized_sha256": first.metadata.get("normalized_csv_sha256"),
        "missing_intervals": first.metadata.get("missing_intervals"),
        "prefix_sha256": _sha(
            _canonical_frame_bytes(frame.iloc[:TRAIN_END][["open", "high", "low", "close"]])
        ),
        "passed": True,
    }


def _anchors() -> list[int]:
    return [t for t in range(TRAIN_START, TRAIN_END, 24) if t + 25 < TRAIN_END]


def _feature(chain: pd.DataFrame, t: int) -> float:
    breadth = np.log1p(chain["median_ntv"].to_numpy(dtype=float)) - np.log1p(
        chain["mean_ntv"].to_numpy(dtype=float)
    )
    baseline = breadth[t - 912 : t - 192]
    recent = breadth[t - 192 : t - 24]
    if len(baseline) != BASELINE_HOURS or len(recent) != RECENT_HOURS:
        return float("nan")
    return float(np.mean(recent) - np.mean(baseline))


def _opportunities(price: pd.DataFrame, chain: pd.DataFrame) -> pd.DataFrame:
    close = price["close"].to_numpy(dtype=float)
    open_price = price["open"].to_numpy(dtype=float)
    rows: list[dict[str, object]] = []
    for t in _anchors():
        if not (close[t - 25] > close[t - 2185]):
            continue
        feature = _feature(chain, t)
        if not math.isfinite(feature):
            continue
        entry = float(open_price[t])
        exit_price = float(open_price[t + 24])
        gross = exit_price / entry - 1.0
        net = gross - ROUND_TRIP_FEE
        adverse = float(np.min(open_price[t : t + 25] / entry - 1.0))
        delay_entry = float(open_price[t + 1])
        delay_exit = float(open_price[t + 25])
        delay_net = delay_exit / delay_entry - 1.0 - ROUND_TRIP_FEE
        delay_adverse = float(np.min(open_price[t + 1 : t + 26] / delay_entry - 1.0))
        rows.append(
            {
                "anchor_index": t,
                "anchor": str(price.index[t]),
                "feature": feature,
                "net": net,
                "adverse": adverse,
                "delay_net": delay_net,
                "delay_adverse": delay_adverse,
            }
        )
    return pd.DataFrame(rows)


def _rho(x: np.ndarray, y: np.ndarray) -> float:
    return float(pd.Series(x).rank(method="average").corr(pd.Series(y).rank(method="average")))


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    sx = float(np.std(x, ddof=0))
    if sx <= 0 or not math.isfinite(sx):
        return float("nan")
    z = (x - float(np.mean(x))) / sx
    return float(np.mean(z * (y - float(np.mean(y)))))


def _tercile(x: np.ndarray, y: np.ndarray) -> tuple[float, int, int]:
    order = np.argsort(x, kind="mergesort")
    n = len(order) // 3
    if n == 0:
        return float("nan"), 0, 0
    return float(np.mean(y[order[-n:]]) - np.mean(y[order[:n]])), n, n


def _bootstrap(
    feature: np.ndarray,
    net: np.ndarray,
    adverse: np.ndarray,
    seed: int,
) -> dict[str, list[float]]:
    n = len(feature)
    if n < BOOTSTRAP_BLOCK:
        keys = ("net_rho", "net_slope", "adverse_rho", "adverse_slope")
        return {key: [float("nan"), float("nan")] for key in keys}
    rng = np.random.default_rng(seed)
    draws = np.empty((BOOTSTRAP_DRAWS, 4), dtype=float)
    max_start = n - BOOTSTRAP_BLOCK + 1
    for i in range(BOOTSTRAP_DRAWS):
        idx: list[int] = []
        while len(idx) < n:
            start = int(rng.integers(0, max_start))
            idx.extend(range(start, start + BOOTSTRAP_BLOCK))
        take = np.asarray(idx[:n], dtype=int)
        draws[i] = (
            _rho(feature[take], net[take]),
            _slope(feature[take], net[take]),
            _rho(feature[take], adverse[take]),
            _slope(feature[take], adverse[take]),
        )
    keys = ("net_rho", "net_slope", "adverse_rho", "adverse_slope")
    return {
        key: [float(np.quantile(draws[:, j], 0.025)), float(np.quantile(draws[:, j], 0.975))]
        for j, key in enumerate(keys)
    }


def _folds(feature: np.ndarray, net: np.ndarray, adverse: np.ndarray) -> dict[str, object]:
    parts = np.array_split(np.arange(len(feature)), 4)
    net_slopes = [_slope(feature[idx], net[idx]) for idx in parts]
    adverse_slopes = [_slope(feature[idx], adverse[idx]) for idx in parts]
    positives = [x for x in net_slopes if math.isfinite(x) and x > 0]
    concentration = max(positives) / sum(positives) if positives and sum(positives) > 0 else 1.0
    return {
        "net_slopes": net_slopes,
        "adverse_slopes": adverse_slopes,
        "positive_net_folds": sum(x > 0 for x in net_slopes if math.isfinite(x)),
        "positive_adverse_folds": sum(x > 0 for x in adverse_slopes if math.isfinite(x)),
        "positive_net_fold_concentration": concentration,
    }


def _evaluate(
    inst: str,
    price: pd.DataFrame,
    chain: pd.DataFrame,
    seed: int,
) -> tuple[dict[str, object], pd.DataFrame]:
    opp = _opportunities(price.iloc[:TRAIN_END], chain.iloc[:TRAIN_END])
    if opp.empty:
        raise ValueError(f"{inst}: no valid training opportunities")
    feature = opp["feature"].to_numpy(dtype=float)
    net = opp["net"].to_numpy(dtype=float)
    adverse = opp["adverse"].to_numpy(dtype=float)
    delay_net = opp["delay_net"].to_numpy(dtype=float)
    delay_adverse = opp["delay_adverse"].to_numpy(dtype=float)

    point = {
        "net_spearman": _rho(feature, net),
        "net_standardized_slope": _slope(feature, net),
        "adverse_spearman": _rho(feature, adverse),
        "adverse_standardized_slope": _slope(feature, adverse),
    }
    net_tercile, low_count, high_count = _tercile(feature, net)
    adverse_tercile, _, _ = _tercile(feature, adverse)
    delay_net_tercile, _, _ = _tercile(feature, delay_net)
    delay_adverse_tercile, _, _ = _tercile(feature, delay_adverse)
    delay = {
        "net_spearman": _rho(feature, delay_net),
        "net_standardized_slope": _slope(feature, delay_net),
        "net_tercile_effect": delay_net_tercile,
        "adverse_spearman": _rho(feature, delay_adverse),
        "adverse_standardized_slope": _slope(feature, delay_adverse),
        "adverse_tercile_effect": delay_adverse_tercile,
    }
    bootstrap = _bootstrap(feature, net, adverse, seed)
    folds = _folds(feature, net, adverse)
    q25, q75 = np.quantile(feature, [0.25, 0.75])
    distinct = int(len(np.unique(feature)))

    replay = _opportunities(price.iloc[:TRAIN_END].copy(), chain.iloc[:TRAIN_END].copy())
    invariant = opp.equals(replay)
    breadth = np.log1p(chain.iloc[:TRAIN_END]["median_ntv"].to_numpy(dtype=float)) - np.log1p(
        chain.iloc[:TRAIN_END]["mean_ntv"].to_numpy(dtype=float)
    )
    structural = {
        "baseline_hours": BASELINE_HOURS,
        "recent_hours": RECENT_HOURS,
        "windows_non_overlapping": True,
        "breadth_all_finite": bool(np.isfinite(breadth).all()),
        "native_units_preserved": True,
        "log1p_replay": True,
        "prefix_invariant": invariant,
    }
    gates = {
        "minimum_opportunities": len(opp) >= 180,
        "feature_support": distinct >= 100 and float(q75 - q25) > 0,
        "tercile_support": low_count >= 50 and high_count >= 50,
        "positive_point_information": all(value > 0 for value in point.values()),
        "positive_tercile_effects": net_tercile > 0 and adverse_tercile > 0,
        "positive_dependence_lower_bounds": all(bounds[0] > 0 for bounds in bootstrap.values()),
        "fold_breadth": folds["positive_net_folds"] >= 3
        and folds["positive_adverse_folds"] >= 3,
        "fold_concentration": folds["positive_net_fold_concentration"] <= 0.60,
        "one_hour_delay": all(value > 0 for value in delay.values()),
        "prefix_invariance": invariant,
        "structural": all(bool(v) for v in structural.values() if isinstance(v, bool)),
    }
    result = {
        "instrument": inst,
        "valid_opportunities": int(len(opp)),
        "distinct_feature_values": distinct,
        "feature_iqr": float(q75 - q25),
        "tercile_counts": {"lower": low_count, "upper": high_count},
        "point_information": point,
        "tercile_effects": {"net": net_tercile, "adverse": adverse_tercile},
        "dependence_intervals_95": bootstrap,
        "folds": folds,
        "one_hour_delay": delay,
        "structural": structural,
        "gates": gates,
        "pass_all_gates": all(gates.values()),
    }
    return result, opp


def _write_terminal(evidence: dict[str, object]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = _json_bytes(evidence)
    (OUTPUT / "evidence.json").write_bytes(payload)
    (OUTPUT / "evidence.sha256").write_text(_sha(payload) + "\n")
    targets = evidence.get("targets", [])
    lines = [
        "# On-chain transfer-size breadth 1H",
        "",
        f"Family: `{FAMILY_ID}`",
        f"Verdict: `{evidence['verdict']}`",
        "Candidate / grid: `0 / 0`",
        f"Sealed OOS accessed: `{str(evidence.get('sealed_oos_accessed', False)).lower()}`",
        "Correction authority: `false`",
        "",
    ]
    if evidence.get("source_failure"):
        lines += ["## Source rejection", "", str(evidence["source_failure"]), ""]
    for target in targets if isinstance(targets, list) else []:
        lines += [
            f"## {target['instrument']}",
            "",
            f"- Valid opportunities: `{target['valid_opportunities']}`",
            f"- Net Spearman: `{target['point_information']['net_spearman']:.6f}`",
            f"- Net standardized slope: `{target['point_information']['net_standardized_slope']:.6f}`",
            f"- Adverse Spearman: `{target['point_information']['adverse_spearman']:.6f}`",
            f"- Adverse standardized slope: `{target['point_information']['adverse_standardized_slope']:.6f}`",
            f"- All gates: `{str(target['pass_all_gates']).lower()}`",
            "",
        ]
    (OUTPUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_dir = OUTPUT / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, object] = {
        "schema_version": "onchain-transfer-size-breadth-1h-v1",
        "family_id": FAMILY_ID,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "bar": "1H",
        "fee_bps_one_way": 5.0,
        "fixed_targets": list(TARGETS),
        "fixed_chain_bindings": {inst: asset for inst, (asset, _) in TARGETS.items()},
        "metrics": list(METRICS),
        "target_returns_accessed": False,
        "strategy_performance_accessed": False,
        "sealed_oos_accessed": False,
        "canonical_mutation": False,
        "correction_authority": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }
    acquired: dict[
        str,
        tuple[pd.DataFrame, pd.DataFrame, dict[str, object], dict[str, object]],
    ] = {}
    try:
        for inst, (asset, _) in TARGETS.items():
            price, price_meta = _acquire_okx(inst, source_dir)
            chain, chain_meta = _acquire_chain(asset, source_dir)
            if not price.index.equals(chain.index):
                raise ValueError(f"{inst}/{asset}: price and chain calendars differ")
            acquired[inst] = (price, chain, price_meta, chain_meta)
    except Exception as exc:
        evidence.update(
            {
                "source_contract_passed": False,
                "source_failure": f"{type(exc).__name__}: {exc}",
                "verdict": SOURCE_REJECT,
            }
        )
        _write_terminal(evidence)
        return

    evidence["source_contract_passed"] = True
    evidence["target_returns_accessed"] = True
    source_manifest: dict[str, object] = {}
    target_results: list[dict[str, object]] = []
    try:
        for inst, (asset, seed) in TARGETS.items():
            price, chain, price_meta, chain_meta = acquired[inst]
            source_manifest[inst] = {"okx": price_meta, "coinmetrics": chain_meta}
            result, opp = _evaluate(inst, price, chain, seed)
            target_results.append(result)
            opp.to_csv(OUTPUT / f"{inst}-training-opportunities.csv", index=False)
    except Exception as exc:
        evidence.update(
            {
                "source_manifest": source_manifest,
                "evaluation_failure": f"{type(exc).__name__}: {exc}",
                "verdict": REJECT,
            }
        )
        _write_terminal(evidence)
        return

    bilateral = all(target["pass_all_gates"] for target in target_results)
    evidence.update(
        {
            "source_manifest": source_manifest,
            "targets": target_results,
            "bilateral_information_pass": bilateral,
            "verdict": ACCEPT if bilateral else REJECT,
        }
    )
    _write_terminal(evidence)


if __name__ == "__main__":
    main()
