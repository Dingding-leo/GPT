#!/usr/bin/env python3
from __future__ import annotations

import math
import random

import research_daily_margin_acceleration_confirmation as research


def fast_bootstrap_delta(candidate: list[float], base: list[float], seed: int) -> dict[str, object]:
    n = len(candidate)
    block = research.BOOT_BLOCK
    block_count = math.ceil(n / block)
    starts = range(0, n - block + 1)
    c_sum = [sum(candidate[i : i + block]) for i in starts]
    b_sum = [sum(base[i : i + block]) for i in starts]
    c_sq = [sum(value * value for value in candidate[i : i + block]) for i in starts]
    b_sq = [sum(value * value for value in base[i : i + block]) for i in starts]
    rng = random.Random(seed)
    mean_deltas: list[float] = []
    sharpe_deltas: list[float] = []
    annualizer = math.sqrt(365.25 * 24)

    for _ in range(research.BOOT_RESAMPLES):
        remaining = n
        cs = bs = css = bss = 0.0
        count = 0
        for _ in range(block_count):
            start = rng.randrange(len(c_sum))
            take = min(block, remaining)
            if take == block:
                cs += c_sum[start]
                bs += b_sum[start]
                css += c_sq[start]
                bss += b_sq[start]
            else:
                cpart = candidate[start : start + take]
                bpart = base[start : start + take]
                cs += sum(cpart)
                bs += sum(bpart)
                css += sum(value * value for value in cpart)
                bss += sum(value * value for value in bpart)
            count += take
            remaining -= take
            if remaining == 0:
                break
        cmean = cs / count
        bmean = bs / count
        cvar = max(0.0, (css - count * cmean * cmean) / (count - 1))
        bvar = max(0.0, (bss - count * bmean * bmean) / (count - 1))
        csh = cmean / math.sqrt(cvar) * annualizer if cvar > 0 else 0.0
        bsh = bmean / math.sqrt(bvar) * annualizer if bvar > 0 else 0.0
        mean_deltas.append((cmean - bmean) * 365.25 * 24)
        sharpe_deltas.append(csh - bsh)

    mean_deltas.sort()
    sharpe_deltas.sort()
    lo = int(0.025 * research.BOOT_RESAMPLES)
    hi = int(0.975 * research.BOOT_RESAMPLES) - 1
    return {
        "annualized_mean_delta_ci95": [mean_deltas[lo], mean_deltas[hi]],
        "sharpe_delta_ci95": [sharpe_deltas[lo], sharpe_deltas[hi]],
    }


research.bootstrap_delta = fast_bootstrap_delta
research.main()
