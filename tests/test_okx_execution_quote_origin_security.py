from __future__ import annotations

import pytest

from gpt_quant.okx_execution_quote import fetch_okx_top_of_book

_INSTRUMENT_SNAPSHOT_SHA256 = (
    "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://www.okx.com",
        "https://127.0.0.1",
        "https://169.254.169.254",
        "https://localhost",
        "https://www.okx.com@evil.example",
        "https://www.okx.com.evil.example",
        "https://www.okx.com:443",
        "https://www.okx.com/api",
        "https://www.okx.com?redirect=https://169.254.169.254",
        "https://www.okx.com#fragment",
    ],
)
def test_fetch_okx_top_of_book_rejects_untrusted_origin_before_io(
    base_url: str,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("untrusted origin reached network or clock boundary")

    with pytest.raises(ValueError, match="trusted public OKX HTTPS origin"):
        fetch_okx_top_of_book(
            instrument_id="BTC-USDT",
            instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
            base_url=base_url,
            get_bytes=forbidden,
            get_json=forbidden,
            now=forbidden,
        )
