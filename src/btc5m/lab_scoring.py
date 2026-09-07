"""Round-level probability diagnostics, without trade-count pseudo-replication."""

import math
from collections import Counter
from typing import Any

EPSILON = 1e-6
MODELS = {"central": "probability", "market": "market_probability", "fast": "fast_probability"}


def _valid_probability(value: Any) -> bool:
    return type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1


def _valid(row: dict[str, Any], key: str) -> bool:
    return (
        row.get("status") == "observed"
        and row.get("outcome") in (0, 1)
        and _valid_probability(row.get(key))
    )


def _wilson(wins: int, n: int) -> tuple[float, float] | None:
    if not n:
        return None
    z = 1.959963984540054
    p, den = wins / n, 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    width = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0, center - width), min(1, center + width)


def score_forecasts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    # One prescheduled forecast per round, regardless of signals, orders or fill count.
    unique = {r["slug"]: r for r in rows}
    models: dict[str, Any] = {}
    for name, key in MODELS.items():
        sample = [r for r in unique.values() if _valid(r, key)]
        bins = []
        for index in range(10):
            group = [r for r in sample if min(9, int(r[key] * 10)) == index]
            n = len(group)
            wins = sum(r["outcome"] for r in group)
            bins.append(
                {
                    "low": index / 10,
                    "high": (index + 1) / 10,
                    "n": n,
                    "mean_probability": sum(r[key] for r in group) / n if n else None,
                    "observed_up": wins / n if n else None,
                    "descriptive_wilson95": _wilson(wins, n),
                }
            )
        n = len(sample)
        models[name] = {
            "n": n,
            "brier": sum((r[key] - r["outcome"]) ** 2 for r in sample) / n if n else None,
            "log_loss": sum(
                -math.log(max(EPSILON, min(1 - EPSILON, r[key] if r["outcome"] else 1 - r[key])))
                for r in sample
            )
            / n
            if n
            else None,
            "log_clipped": sum(r[key] < EPSILON or r[key] > 1 - EPSILON for r in sample),
            "bins": bins,
        }
    comparisons = {}
    for name, a, b in (
        ("central_vs_market", "probability", "market_probability"),
        ("fast_vs_central", "fast_probability", "probability"),
    ):
        paired = [r for r in unique.values() if _valid(r, a) and _valid(r, b)]
        comparisons[name] = {
            "n": len(paired),
            "brier_difference": sum(
                (r[a] - r["outcome"]) ** 2 - (r[b] - r["outcome"]) ** 2 for r in paired
            )
            / len(paired)
            if paired
            else None,
        }
    return {
        "expected_rounds": len(unique),
        "missing_labels": sum(r.get("outcome") not in (0, 1) for r in unique.values()),
        "statuses": dict(Counter(r.get("status", "missing") for r in unique.values())),
        "models": models,
        "comparisons": comparisons,
        "method": "One end-minus120s observation per round; at most 2s late. Lower Brier/log loss is better. Differences use the same rounds. Wilson bars are descriptive independent-round intervals, not time-series or multiple-testing significance. Log loss clips at 1e-6; Brier does not.",
    }
