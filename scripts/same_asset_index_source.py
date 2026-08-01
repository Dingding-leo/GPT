"""Compatibility names for the immutable reused temporal-metrics core."""
from onchain_activity_source import (
    BOOTSTRAP_BLOCK,
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    FEE,
    FULL_END,
    HOUR_MS,
    OOS_END,
    START_MS,
    TRAIN_END,
    WARMUP_END,
    PriceSeries,
    canonical_bytes,
    sha256_bytes,
    utc_iso,
)

Series = PriceSeries

__all__ = [
    "BOOTSTRAP_BLOCK",
    "BOOTSTRAP_DRAWS",
    "BOOTSTRAP_SEED",
    "FEE",
    "FULL_END",
    "HOUR_MS",
    "OOS_END",
    "START_MS",
    "TRAIN_END",
    "WARMUP_END",
    "Series",
    "canonical_bytes",
    "sha256_bytes",
    "utc_iso",
]
