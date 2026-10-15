"""Offline regression tests for GPT POWER STOCKS scanner helpers."""
import importlib.util
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
# yfinance is a runtime dependency; stub it only when running tests without installing
# requirements. These tests never download market data.
if importlib.util.find_spec("yfinance") is None:
    yf_stub = types.ModuleType("yfinance")
    yf_stub.download = lambda *args, **kwargs: pd.DataFrame()
    sys.modules["yfinance"] = yf_stub

spec = importlib.util.spec_from_file_location("scanner_under_test", ROOT / "scanner.py")
scanner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scanner
spec.loader.exec_module(scanner)


class ScannerRegressionTests(unittest.TestCase):
    def test_import_does_not_fetch_fno_data(self):
        self.assertEqual(scanner.FNO_UNIVERSE_SOURCE, "not loaded yet")
        self.assertEqual(scanner.FNO_SYMBOL_SET, set())

    def test_fno_payload_excludes_indices_and_requires_full_list(self):
        rows = [{"symbol": f"STOCK{i}"} for i in range(150)]
        rows += [{"symbol": "NIFTY"}, {"symbol": "BANKNIFTY"}]
        result = scanner._extract_fno_from_payload({"UnderlyingList": rows, "IndexList": [{"symbol": "NIFTY"}]})
        self.assertEqual(len(result), 150)
        self.assertNotIn("NIFTY", result)
        self.assertEqual(scanner._extract_fno_from_payload([{"symbol": "ONLYONE"}]), [])

    def test_clean_ohlcv_normalizes_columns_and_index(self):
        idx = pd.date_range("2026-10-15 09:15", periods=3, freq="5min")
        frame = pd.DataFrame({
            "open": [100, 101, 102], "high": [102, 103, 104],
            "low": [99, 100, 101], "close": [101, 102, 103],
            "volume": [10, 20, 30],
        }, index=idx)
        clean = scanner.clean_ohlcv(frame)
        self.assertEqual(list(clean.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(str(clean.index.tz), "Asia/Kolkata")
        self.assertEqual(len(clean), 3)

    def test_incomplete_five_minute_bar_is_removed(self):
        now = datetime(2026, 10, 15, 9, 27, tzinfo=scanner.IST)
        idx = pd.DatetimeIndex([
            pd.Timestamp("2026-10-15 09:15", tz=scanner.IST),
            pd.Timestamp("2026-10-15 09:20", tz=scanner.IST),
            pd.Timestamp("2026-10-15 09:25", tz=scanner.IST),
        ])
        frame = pd.DataFrame({
            "Open": [1, 2, 3], "High": [2, 3, 4], "Low": [0, 1, 2],
            "Close": [1, 2, 3], "Volume": [10, 20, 30],
        }, index=idx)
        result = scanner.remove_incomplete_5m_bars(frame, now)
        self.assertEqual(len(result), 2)
        self.assertEqual(result.index[-1].strftime("%H:%M"), "09:20")

    def test_rsi_handles_monotonic_gain_and_loss(self):
        gains = pd.Series(range(1, 20), dtype=float)
        losses = pd.Series(range(20, 1, -1), dtype=float)
        self.assertEqual(scanner.calc_rsi(gains, length=5).iloc[-1], 100.0)
        self.assertEqual(scanner.calc_rsi(losses, length=5).iloc[-1], 0.0)

    def test_confirmation_audit_keeps_confirmed_state_when_time_exists(self):
        power = {"breakoutConfirmed": True, "status": "BREAKOUT CONFIRMED", "detectTime": ""}
        result = scanner.apply_confirmation_audit(power, "10:05")
        self.assertTrue(result["breakoutConfirmed"])
        self.assertEqual(result["status"], "BREAKOUT CONFIRMED")
        self.assertEqual(result["detectTime"], "10:05")

    def test_confirmation_audit_prevents_contradictory_confirmed_label(self):
        power = {"breakoutConfirmed": True, "status": "BREAKOUT CONFIRMED", "detectTime": ""}
        result = scanner.apply_confirmation_audit(power, None)
        self.assertFalse(result["breakoutConfirmed"])
        self.assertEqual(result["status"], "CONFIRMATION NOT VERIFIED")
        self.assertEqual(result["detectTime"], "Not confirmed")

    def test_json_safe_converts_nonfinite_values(self):
        payload = {"x": float("nan"), "y": np.float64(np.inf), "z": np.int64(2)}
        result = scanner.to_json_safe(payload)
        self.assertIsNone(result["x"])
        self.assertIsNone(result["y"])
        self.assertEqual(result["z"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
