from __future__ import annotations

from email.message import Message
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import BaseHandler, Request, addinfourl, build_opener

import pytest

from gpt_quant.okx_execution_quote import _RejectRedirects


class _RedirectingHTTPSHandler(BaseHandler):
    handler_order = 100

    def https_open(self, request: Request):
        headers = Message()
        headers["Location"] = "https://169.254.169.254/latest/meta-data/"
        response = addinfourl(BytesIO(b""), headers, request.full_url, 302)
        response.msg = "Found"
        return response


def test_public_okx_transport_rejects_cross_origin_redirect_before_following() -> None:
    opener = build_opener(_RejectRedirects(), _RedirectingHTTPSHandler())
    request = Request("https://www.okx.com/api/v5/market/books?instId=BTC-USDT&sz=1")

    with pytest.raises(HTTPError) as exc_info:
        opener.open(request)

    assert exc_info.value.code == 302
    assert exc_info.value.geturl() == request.full_url
