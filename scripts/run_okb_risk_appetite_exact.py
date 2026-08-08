from __future__ import annotations

from scripts import run_okb_risk_appetite as base

SOURCE_SAFETY_PAGES = 64


def _fetch_with_frozen_page_allowance(inst_id: str, *, end: str) -> object:
    return base.fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=base.START,
        end=end,
        limit=100,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=SOURCE_SAFETY_PAGES,
    )


def main() -> int:
    base._fetch = _fetch_with_frozen_page_allowance
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
