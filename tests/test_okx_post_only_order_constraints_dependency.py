from __future__ import annotations

import gpt_quant.okx_post_only_order_constraints as post_only_constraints
from gpt_quant.okx_order_constraints import validate_okx_spot_limit_order_constraints


def test_post_only_gate_uses_canonical_okx_limit_constraint() -> None:
    assert (
        post_only_constraints.validate_okx_spot_limit_order_constraints
        is validate_okx_spot_limit_order_constraints
    )
