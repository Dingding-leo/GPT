"""Compatibility names for the immutable reused temporal-metrics core."""
import onchain_activity_source as source
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

# The first immutable request was rejected before data access.  Retrying with a
# smaller page is a transport repair only: it changes neither timestamps nor values.
source.CM_PAGE_SIZE = 2_000
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
