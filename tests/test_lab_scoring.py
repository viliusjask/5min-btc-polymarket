from btc5m.lab_scoring import score_forecasts


def row(slug, p, market, y, fast=None):
    return {
        "slug": slug,
        "status": "observed",
        "probability": p,
        "market_probability": market,
        "fast_probability": fast,
        "outcome": y,
    }


def test_scoring_uses_one_round_and_common_forecast_sample():
    report = score_forecasts(
        [
            row("a", 0.8, 0.5, 1, 0.9),
            row("b", 0.2, 0.5, 0),
            {"slug": "c", "status": "missing", "outcome": 1},
        ]
    )
    assert report["expected_rounds"] == 3
    assert report["models"]["central"]["n"] == 2
    assert abs(report["models"]["central"]["brier"] - 0.04) < 1e-12
    assert report["models"]["market"]["brier"] == 0.25
    assert report["comparisons"]["fast_vs_central"]["n"] == 1
    assert abs(report["comparisons"]["fast_vs_central"]["brier_difference"] + 0.03) < 1e-12
    assert sum(b["n"] for b in report["models"]["central"]["bins"]) == 2


def test_duplicate_missing_and_extreme_predictions_are_not_fake_certainty():
    rows = [
        row("a", 1, 0.6, 0),
        row("a", 1, 0.6, 0),
        row("b", None, 0.5, 1),
        row("c", 0.9, 0.5, None),
    ]
    report = score_forecasts(rows)
    assert report["expected_rounds"] == 3
    assert report["models"]["central"]["n"] == 1
    assert report["models"]["central"]["brier"] == 1
    assert report["models"]["central"]["log_clipped"] == 1
    assert report["missing_labels"] == 1
    assert score_forecasts([])["models"]["central"]["brier"] is None
