"""Forex and commodity profiles, sizing, and the risk check. Stocks stay stocks."""

import datetime
import unittest

from _load import load

markets = load("trader-scanner", "markets")
size = load("trader-budget", "size")
check = load("trader-risk", "check")

TODAY = "2026-10-19"
NOW = "2026-10-19 10:15"


def budget(**over):
    c = {
        "budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 75, "max_order_usd": 4000,
        "min_order_usd": 5, "max_loss_per_trade_usd": 50, "max_daily_loss_usd": 150,
        "max_trades_per_day": 3, "min_reward_risk": 1.0, "require_stop": True,
        "no_entries_before": "09:45", "no_entries_after": "15:30", "flat_by": "15:55",
        "paper": True, "allow_leverage": False, "max_leverage": 1, "fx_usd_per_quote": {},
    }
    c.update(over)
    return c


def fx_plan(symbol="EURUSD=X", entry=1.085, stop=1.080, target=1.090):
    return {"symbol": symbol, "side": "buy", "date": TODAY, "setup": "orb",
            "entry": entry, "stop": stop, "target": target}


class Profiles(unittest.TestCase):
    def test_stocks_stay_stocks(self):
        for sym in ("TSLA", "BRK.B", "SIL", "CL", "NG", "GC"):
            self.assertEqual(markets.classify(sym)["market"], "equity", sym)
        self.assertEqual(markets.classify("BRK.B")["symbol"], "BRK.B")
        self.assertEqual(markets.classify("CL")["symbol"], "CL")
        self.assertNotEqual(markets.classify("CL")["yahoo"], "CL=F")

    def test_aliases_and_pairs(self):
        oil = markets.classify("OIL")
        self.assertEqual((oil["market"], oil["symbol"], oil["point_value"]), ("commodity", "CL=F", 1000.0))
        self.assertEqual(markets.classify("SIL=F")["market"], "commodity")
        for raw in ("EURUSD", "EUR/USD", "eurusd=x"):
            prof = markets.classify(raw)
            self.assertEqual(prof["market"], "forex", raw)
            self.assertEqual(prof["symbol"], "EURUSD=X")
            self.assertEqual(prof["decimals"], 5)
            self.assertEqual(markets.usd_per_point(prof, 1.085), 1000.0)
        jpy = markets.classify("USDJPY")
        self.assertEqual(jpy["decimals"], 3)
        self.assertAlmostEqual(markets.usd_per_point(jpy, 150), 1000.0 / 150.0)
        gold = markets.classify("GOLD")
        self.assertEqual((gold["market"], gold["symbol"], gold["unit"], gold["point_value"]),
                         ("commodity", "XAUUSD=X", "ounce", 1.0))
        self.assertEqual(markets.classify("XAUUSD")["symbol"], "XAUUSD=X")
        gc = markets.classify("GC=F")
        self.assertEqual((gc["name"], gc["point_value"], gc["unit"]), ("Gold", 100.0, "contract"))

    def test_sessions_and_holidays(self):
        ny = markets.classify("EURUSD")
        london = markets.classify("EURUSD", session="london")
        self.assertEqual(ny["open"], datetime.time(8, 0))
        self.assertEqual(london["open"], datetime.time(3, 0))
        sat = datetime.date(2026, 11, 7)
        thanks = datetime.date(2026, 11, 26)
        self.assertFalse(markets.is_open_day(ny, sat)[0])
        self.assertTrue(markets.is_open_day(ny, thanks)[0])
        gc = markets.classify("GC=F")
        self.assertFalse(markets.is_open_day(gc, thanks)[0])
        self.assertTrue(markets.is_open_day(gc, datetime.date(2026, 10, 19))[0])

    def test_forex_window_is_not_the_stock_bell(self):
        prof = markets.classify("EURUSD")
        early = datetime.datetime(2026, 10, 19, 8, 30)
        reasons, _warns = markets.window_reasons(early, budget(), prof)
        self.assertEqual(reasons, [])
        closed = datetime.datetime(2026, 11, 26, 10, 15)
        fx_reasons, _w = markets.window_reasons(closed, budget(), prof)
        self.assertEqual(fx_reasons, [])
        gc_reasons, _w = markets.window_reasons(closed, budget(), markets.classify("GC=F"))
        self.assertTrue(gc_reasons)
        self.assertIn("closed", gc_reasons[0])


class Sizing(unittest.TestCase):
    def test_eurusd_keeps_pips_and_is_not_bound_by_the_50_dollar_loss(self):
        s = size.size_trade(fx_plan(), budget(), today=TODAY)
        self.assertEqual(s["market"], "forex")
        self.assertIsNone(s["refusal"])
        self.assertGreater(s["qty"], 0)
        self.assertNotEqual(s["bound_by"], "max loss")
        self.assertAlmostEqual(s["entry"], 1.085, places=5)
        self.assertAlmostEqual(s["stop"], 1.080, places=5)
        self.assertNotAlmostEqual(s["entry"], 1.09, places=4)
        self.assertAlmostEqual(s["risk_per_share"], 5.0, places=2)
        self.assertGreater(s["cost"], 1000)

    def test_a_full_crude_contract_does_not_fit_the_max_loss(self):
        s = size.size_trade(fx_plan("CL=F", 70.0, 69.0, 72.0), budget(), today=TODAY)
        self.assertEqual(s["qty"], 0)
        self.assertIn("max loss", s["refusal"])
        self.assertIn("MCL=F", s["refusal"])

    def test_a_cross_without_a_dollar_rate_is_refused(self):
        with self.assertRaises(size.SizeError) as cm:
            size.size_trade(fx_plan("EURGBP", 0.85000, 0.84500, 0.86000), budget(), today=TODAY)
        self.assertIn("fx_usd_per_quote", str(cm.exception))


class RiskCheck(unittest.TestCase):
    def test_eurusd_bracket_can_pass(self):
        order = {
            "symbol": "EURUSD=X", "side": "buy", "qty": "2", "type": "limit", "time_in_force": "day",
            "order_class": "bracket", "limit_price": "1.08500",
            "take_profit_limit_price": "1.09000", "stop_loss_stop_price": "1.08000",
            "plan": {"entry": 1.085, "stop": 1.080, "target": 1.090},
        }
        res = check.check([order], budget(), now=check.parse_now(NOW))
        text = " | ".join(res["results"][0]["reasons"])
        self.assertNotIn("stocks and ETFs only", text)
        self.assertEqual(res["results"][0]["verdict"], "PASS", text)

    def test_crypto_is_still_refused(self):
        order = {"symbol": "BTC/USD", "side": "buy", "qty": "1", "type": "market", "time_in_force": "day",
                 "plan": {"entry": 100, "stop": 90, "target": 120},
                 "stop_loss_stop_price": "90", "take_profit_limit_price": "120", "order_class": "bracket"}
        res = check.check([order], budget(), now=check.parse_now(NOW))
        text = " | ".join(res["results"][0]["reasons"])
        self.assertIn("stocks and ETFs only", text)


if __name__ == "__main__":
    unittest.main()
