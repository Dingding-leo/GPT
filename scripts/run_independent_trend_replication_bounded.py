from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from typing import Any

import pandas as pd

import run_independent_trend_replication as experiment
from gpt_quant.okx_1h import fetch_okx_one_hour_candles as fetch_okx_one_hour_candles_base
from gpt_quant.okx_execution_quote import _read_public_response


def _end_anchored_bytes_getter(end: pd.Timestamp | str) -> Callable[[str, float], bytes]:
    """Anchor the first backwards page immediately after the frozen end candle.

    OKX ``history-candles`` returns records earlier than the exclusive ``after``
    timestamp. The canonical downloader otherwise starts from the latest public
    candle, so a page budget derived from a bounded historical interval cannot
    reach that interval. This transport-only wrapper changes no returned row:
    it adds ``after=end+1H`` to the first request, after which the canonical
    downloader continues with its validated oldest-row cursor.
    """

    end_timestamp = pd.Timestamp(end)
    if end_timestamp.tzinfo is None:
        end_timestamp = end_timestamp.tz_localize("UTC")
    else:
        end_timestamp = end_timestamp.tz_convert("UTC")
    if end_timestamp != end_timestamp.floor("h"):
        raise ValueError("end must align to an exact UTC hour")
    initial_after = str(int((end_timestamp + pd.Timedelta(hours=1)).timestamp() * 1_000))
    first_request = True

    def get_bytes(url: str, timeout: float) -> bytes:
        nonlocal first_request
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if first_request:
            if any(key == "after" for key, _ in query):
                raise AssertionError("first bounded history request unexpectedly already has after")
            query.append(("after", initial_after))
            first_request = False
        rewritten = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
        )
        return _read_public_response(rewritten, timeout)

    return get_bytes


def fetch_bounded_one_hour_candles(*, end: pd.Timestamp | str, **kwargs: Any):
    if "get_json" in kwargs or "get_bytes" in kwargs:
        raise ValueError("replication fetch does not accept an external transport override")
    return fetch_okx_one_hour_candles_base(
        end=end,
        get_bytes=_end_anchored_bytes_getter(end),
        **kwargs,
    )


def main() -> int:
    experiment.fetch_okx_one_hour_candles = fetch_bounded_one_hour_candles
    return experiment.main()


if __name__ == "__main__":
    raise SystemExit(main())
