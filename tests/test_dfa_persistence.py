from scripts.run_dfa_persistence import (
    BOOTSTRAP_BLOCK,
    BOOTSTRAP_DRAWS,
    DFA_SCALES,
    DFA_WINDOW,
    FEATURE_EMBARGO_HOURS,
    FEE_ONE_WAY,
    ROUND_TRIP_FEE,
    TARGETS,
    TRAIN_END,
    _training_anchors,
)


def test_frozen_dfa_contract_is_exact() -> None:
    assert DFA_WINDOW == 720
    assert DFA_SCALES == (12, 24, 48, 72, 120, 144, 180)
    assert all(DFA_WINDOW % scale == 0 for scale in DFA_SCALES)
    assert FEATURE_EMBARGO_HOURS == 25
    assert TARGETS == ("ATOM-USDT", "LINK-USDT")


def test_frozen_cost_and_dependence_contract_is_exact() -> None:
    assert FEE_ONE_WAY == 0.0005
    assert ROUND_TRIP_FEE == 0.001
    assert BOOTSTRAP_DRAWS == 5_000
    assert BOOTSTRAP_BLOCK == 7


def test_training_and_delay_labels_remain_before_sealed_oos() -> None:
    anchors = _training_anchors()
    assert anchors
    assert all(anchor + 25 < TRAIN_END for anchor in anchors)
    assert anchors == sorted(anchors)
    assert all(
        right - left == 24 for left, right in zip(anchors, anchors[1:], strict=False)
    )
