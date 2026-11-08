"""Forex and commodity profiles, sizing, and the risk check. Stocks stay stocks."""

import contextlib
import datetime
import io
import json
import os
import tempfile
import unittest

from _load import load

markets = load("trader-scanner", "markets")
size = load("trader-budget", "size")
check = load("trader-risk", "check")
news = load("trader-news", "news")

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


# ForexFactory's weekly feed shape. NOW is 10:15 New York = 14:15 UTC.
FF_FEED = [
    {"title": "Retail Sales m/m", "country": "USD", "date": "2026-10-19T10:30:00-04:00", "impact": "High",
     "forecast": "0.4%", "previous": "0.6%"},
    {"title": "BOJ Gov Speaks", "country": "JPY", "date": "2026-10-19T10:20:00-04:00", "impact": "High",
     "forecast": "", "previous": ""},
    {"title": "German ZEW", "country": "EUR", "date": "2026-10-19T05:00:00-04:00", "impact": "Medium",
     "forecast": "", "previous": ""},
    {"title": "Bad row", "country": "USD", "date": "not a date", "impact": "High"},
    {"title": "FOMC Minutes", "country": "USD", "date": "2026-10-22T14:00:00-04:00", "impact": "High",
     "forecast": "", "previous": ""},
]


def fx_order(symbol="EURUSD=X"):
    return {
        "symbol": symbol, "side": "buy", "qty": "2", "type": "limit", "time_in_force": "day",
        "order_class": "bracket", "limit_price": "1.08500",
        "take_profit_limit_price": "1.09000", "stop_loss_stop_price": "1.08000",
        "plan": {"entry": 1.085, "stop": 1.080, "target": 1.090},
    }


class TradingViewLinks(unittest.TestCase):
    def test_symbols(self):
        tv = markets.tradingview_symbol
        self.assertEqual(tv("TSLA"), "TSLA")
        self.assertEqual(tv("BRK-B"), "BRK.B")
        self.assertEqual(tv("EURUSD"), "FX_IDC:EURUSD")
        self.assertEqual(tv("GOLD"), "OANDA:XAUUSD")
        self.assertEqual(tv("CL=F"), "NYMEX:CL1!")
        self.assertEqual(tv("GC=F"), "COMEX:GC1!")
        self.assertEqual(markets.tradingview_url("EURUSD"),
                         "https://www.tradingview.com/chart/?symbol=FX_IDC%3AEURUSD")


class Calendar(unittest.TestCase):
    def setUp(self):
        self.events = markets.parse_calendar(json.dumps(FF_FEED).encode())

    def test_parse_to_utc_and_skip_bad_dates(self):
        self.assertEqual(len(self.events), 4)
        first = self.events[0]
        self.assertEqual((first["currency"], first["time"]), ("EUR", "2026-10-19T09:00:00Z"))
        self.assertEqual(markets.calendar_currencies("EURUSD"), {"EUR", "USD"})
        self.assertEqual(markets.calendar_currencies("CL=F"), {"USD"})

    def test_blackout(self):
        now = datetime.datetime(2026, 10, 19, 14, 15)
        hits = markets.news_blackout(self.events, now, "EURUSD", 30)
        self.assertEqual([e["title"] for e in hits], ["Retail Sales m/m"])
        self.assertEqual(markets.news_blackout(self.events, now, "EURUSD", 10), [])
        jpy = markets.news_blackout(self.events, now, "USDJPY", 30)
        self.assertEqual(len(jpy), 2)

    def test_risk_blocks_fx_entry_near_high_impact(self):
        res = check.check([fx_order()], budget(), now=check.parse_now(NOW), calendar=self.events)
        r = res["results"][0]
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertIn("Retail Sales m/m", " | ".join(r["reasons"]))

    def test_risk_passes_outside_the_window_or_when_off(self):
        later = check.parse_now("2026-10-19 11:30")
        res = check.check([fx_order()], budget(), now=later, calendar=self.events)
        self.assertEqual(res["results"][0]["verdict"], "PASS", res["results"][0]["reasons"])
        res = check.check([fx_order()], budget(news_blackout_minutes=0), now=check.parse_now(NOW),
                          calendar=self.events)
        self.assertEqual(res["results"][0]["verdict"], "PASS")

    def test_news_calendar_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "ff_calendar_thisweek.json"), "w", encoding="utf-8") as fh:
                json.dump(FF_FEED, fh)
            out_file = os.path.join(tmp, "calendar.json")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = news.main(["--calendar", "--tickers", "EURUSD", "--impact", "High", "--offline", tmp,
                                  "--now", "2026-10-19T13:00:00Z", "--calendar-out", out_file])
            text = buf.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("10:30 ET  USD  High    Retail Sales m/m", text)
            self.assertNotIn("BOJ", text)
            self.assertNotIn("ZEW", text)
            with open(out_file, encoding="utf-8") as fh:
                self.assertEqual(len(json.load(fh)["events"]), 4)


if __name__ == "__main__":
    unittest.main()
