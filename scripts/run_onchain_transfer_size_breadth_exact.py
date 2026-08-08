from __future__ import annotations

import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_PATH = Path(__file__).with_name("run_onchain_transfer_size_breadth.py")
spec = importlib.util.spec_from_file_location("onchain_transfer_size_breadth_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load frozen on-chain transfer-size-breadth implementation")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def _catalog_contract(asset: str, source_dir: Path) -> dict[str, object]:
    """Replay the Community catalog deterministically until the frozen asset is found.

    This is the single permitted post-source-inspection correctness repair for #1093.
    It changes no target, metric, frequency, calendar, feature, label, fee or gate.
    """

    url: str | None = f"{base.CM_ROOT}/catalog-v2/asset-metrics"
    seen: set[str] = set()
    pages: list[dict[str, object]] = []
    match: dict[str, object] | None = None
    page_no = 0

    while url:
        if url in seen:
            raise ValueError(f"{asset}: Coin Metrics catalog pagination loop")
        seen.add(url)
        raw, payload, final_url = base._http_get(url)
        page_path = source_dir / f"coinmetrics-{asset}-catalog-page-{page_no:02d}.json"
        page_path.write_bytes(raw)
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("Coin Metrics catalog response missing data list")
        pages.append(
            {
                "request_url": final_url,
                "response_sha256": base._sha(raw),
                "rows": len(data),
            }
        )
        for row in data:
            if isinstance(row, dict) and row.get("asset") == asset:
                match = row
                break
        if match is not None:
            break

        next_url = payload.get("next_page_url")
        if next_url in (None, ""):
            url = None
        elif isinstance(next_url, str):
            parsed = urlparse(next_url)
            if parsed.scheme != "https" or parsed.hostname != "community-api.coinmetrics.io":
                raise ValueError(f"{asset}: catalog next_page_url left Community host")
            query = parse_qs(parsed.query, keep_blank_values=True)
            if any(key in query for key in ("api_key", "apikey", "token")):
                raise ValueError(f"{asset}: catalog next_page_url contains credential")
            url = next_url
        else:
            raise ValueError(f"{asset}: invalid catalog next_page_url")
        page_no += 1

    if match is None:
        raise ValueError(f"{asset}: absent from complete credential-free catalog traversal")
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
        community_frequencies = [
            str(item.get("frequency"))
            for item in frequencies
            if isinstance(item, dict)
            and item.get("community") is True
            and item.get("frequency") is not None
        ]
        available[name] = community_frequencies

    for metric in base.METRICS:
        if metric not in available or "1h" not in available[metric]:
            raise ValueError(
                f"{asset}: {metric} 1h not declared as Community-available by catalog"
            )

    return {
        "asset": asset,
        "pages": pages,
        "page_count": len(pages),
        "metrics": {metric: available[metric] for metric in base.METRICS},
        "passed": True,
    }


base._catalog_contract = _catalog_contract
base.main()
