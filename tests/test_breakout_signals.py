from app.signals.features import compute_features


def _make_candles(closes):
    candles = []
    for idx, close in enumerate(closes):
        candles.append(
            {
                "t": 1_700_000_000 + idx * 60,
                "o": close * 0.995,
                "h": close * 1.01,
                "l": close * 0.99,
                "c": close,
                "v": 100.0 + idx,
            }
        )
    return candles


def test_breakout_strict_true_on_compression_and_expansion():
    candles = _make_candles([1.00, 1.01, 1.02, 1.08])
    features = compute_features(
        candles,
        lookback=3,
        vol_multiplier=1.0,
        compression_max_range_ratio=1.05,
        compression_lookback=3,
        expansion_min_pct=0.05,
        expansion_reference="highest_close",
    )
    assert features["range_compressed"] is True
    assert features["price_expanded"] is True
    assert features["breakout_strict"] is True


def test_breakout_strict_false_when_no_compression():
    candles = _make_candles([1.00, 1.30, 1.10, 1.25])
    features = compute_features(
        candles,
        lookback=3,
        vol_multiplier=1.0,
        compression_max_range_ratio=1.10,
        compression_lookback=3,
        expansion_min_pct=0.05,
        expansion_reference="highest_close",
    )
    assert features["range_compressed"] is False
    assert features["breakout_strict"] is False


def test_breakout_strict_false_when_no_expansion():
    candles = _make_candles([1.00, 1.01, 1.02, 1.03])
    features = compute_features(
        candles,
        lookback=3,
        vol_multiplier=1.0,
        compression_max_range_ratio=1.10,
        compression_lookback=3,
        expansion_min_pct=0.06,
        expansion_reference="highest_close",
    )
    assert features["range_compressed"] is True
    assert features["price_expanded"] is False
    assert features["breakout_strict"] is False
