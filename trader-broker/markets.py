"""Forex pairs and commodity contracts for the day-trader tools.

Stocks stay stocks: classify("TSLA") and classify("BRK.B") return market
"equity" and the other tools keep their own NYSE calendar. This module is
only the extra path for a currency pair or a futures contract.

Forex day session (New York time), pick one:
  newyork  08:00 to 17:00 (default; the cash session through the 17:00 rollover)
  london   03:00 to 12:00

Commodity hours are the US day session for that product (also New York), on
the same holiday list as the NYSE. Spot metals (XAUUSD and the rest) trade
like forex and use the forex session. A full-size futures contract is sized
in contracts; forex is sized in micro lots of 1,000 units of the base
currency; spot metal is sized in ounces.

Nothing here is a forecast or a broker. Point values are the standard
contract sizes (dollars per 1.0 move in the Yahoo price, per one contract).
"""

import datetime
import re
import urllib.parse

CURRENCIES = {
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "SEK", "NOK",
    "DKK", "SGD", "HKD", "MXN", "ZAR", "TRY", "CNH", "CNY", "PLN",
}
METALS = {"XAU", "XAG", "XPT", "XPD"}

# NYSE holiday dates, used for CME day sessions (metals, energy, grains, softs).
# Forex does not use this list: it is open on US holidays.
CME_HOLIDAYS = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King, Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth National Independence Day",
    "2026-07-03": "Independence Day (observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day",
    "2027-01-18": "Martin Luther King, Jr. Day",
    "2027-02-15": "Washington's Birthday",
    "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth National Independence Day (observed)",
    "2027-07-05": "Independence Day (observed)",
    "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day",
    "2027-12-24": "Christmas Day (observed)",
}

STOCK_BEFORE = "09:45"
STOCK_AFTER = "15:30"
STOCK_FLAT = "15:55"

# A full-size contract's smaller cousin, named in a refusal when one contract
# is too big for the account.
MICRO_OF = {"GC=F": "MGC=F", "SI=F": "SIL=F", "CL=F": "MCL=F"}


def _shift_min(h, m, delta):
    base = h * 60 + m + delta
    return "%02d:%02d" % divmod(base, 60)


def _bounds(oh, om, ch, cm):
    """One same-day session: open, close, 5-minute bar count, entry window."""
    bars = ((ch * 60 + cm) - (oh * 60 + om)) // 5
    return {
        "open": datetime.time(oh, om),
        "close": datetime.time(ch, cm),
        "open_min": oh * 60 + om,
        "close_min": ch * 60 + cm,
        "bars": bars,
        "no_entries_before": _shift_min(oh, om, 15),
        "no_entries_after": _shift_min(ch, cm, -30),
        "flat_by": _shift_min(ch, cm, -5),
    }


FOREX_SESSIONS = {
    "newyork": _bounds(8, 0, 17, 0),
    "london": _bounds(3, 0, 12, 0),
}
SESSION_ALIAS = {"ny": "newyork", "new_york": "newyork", "us": "newyork"}

# US day session by product group. Electronic hours run overnight; the tools
# use this window so an opening range has one open and one close on the same date.
METAL_HOURS = _bounds(8, 20, 13, 30)
ENERGY_HOURS = _bounds(9, 0, 14, 30)
GRAIN_HOURS = _bounds(9, 30, 14, 20)
SOFT_HOURS = _bounds(8, 0, 13, 30)
LIVESTOCK_HOURS = _bounds(9, 30, 14, 5)
GENERIC_HOURS = _bounds(9, 0, 17, 0)


def _contract(yahoo, name, point_value, hours, decimals, tick, group):
    return {
        "yahoo": yahoo, "name": name, "point_value": point_value, "hours": hours,
        "decimals": decimals, "tick": tick, "group": group, "spot": False,
    }


# point_value: USD profit for a 1.0 move in the Yahoo price, per one contract.
# Grains, coffee, cotton, sugar, cattle and hogs are quoted in cents on Yahoo,
# so 1.0 is one cent and the point value is the cent-value of the contract.
COMMODITY_TABLE = {
    "MGC=F": _contract("MGC=F", "Micro gold", 10.0, METAL_HOURS, 2, 0.1, "metals"),
    "GC=F": _contract("GC=F", "Gold", 100.0, METAL_HOURS, 2, 0.1, "metals"),
    "SIL=F": _contract("SIL=F", "Micro silver", 1000.0, METAL_HOURS, 3, 0.005, "metals"),
    "SI=F": _contract("SI=F", "Silver", 5000.0, METAL_HOURS, 3, 0.005, "metals"),
    "HG=F": _contract("HG=F", "Copper", 25000.0, METAL_HOURS, 4, 0.0005, "metals"),
    "PL=F": _contract("PL=F", "Platinum", 50.0, METAL_HOURS, 2, 0.1, "metals"),
    "PA=F": _contract("PA=F", "Palladium", 100.0, METAL_HOURS, 2, 0.1, "metals"),
    "MCL=F": _contract("MCL=F", "Micro WTI crude", 100.0, ENERGY_HOURS, 2, 0.01, "energy"),
    "CL=F": _contract("CL=F", "WTI crude", 1000.0, ENERGY_HOURS, 2, 0.01, "energy"),
    "BZ=F": _contract("BZ=F", "Brent crude", 1000.0, ENERGY_HOURS, 2, 0.01, "energy"),
    "NG=F": _contract("NG=F", "Natural gas", 10000.0, ENERGY_HOURS, 3, 0.001, "energy"),
    "HO=F": _contract("HO=F", "Heating oil", 42000.0, ENERGY_HOURS, 4, 0.0001, "energy"),
    "RB=F": _contract("RB=F", "RBOB gasoline", 42000.0, ENERGY_HOURS, 4, 0.0001, "energy"),
    "ZC=F": _contract("ZC=F", "Corn", 50.0, GRAIN_HOURS, 2, 0.25, "grains"),
    "ZW=F": _contract("ZW=F", "Wheat", 50.0, GRAIN_HOURS, 2, 0.25, "grains"),
    "ZS=F": _contract("ZS=F", "Soybeans", 50.0, GRAIN_HOURS, 2, 0.25, "grains"),
    "KC=F": _contract("KC=F", "Coffee", 375.0, SOFT_HOURS, 2, 0.05, "softs"),
    "CT=F": _contract("CT=F", "Cotton", 500.0, SOFT_HOURS, 2, 0.01, "softs"),
    "SB=F": _contract("SB=F", "Sugar", 1120.0, SOFT_HOURS, 2, 0.01, "softs"),
    "CC=F": _contract("CC=F", "Cocoa", 10.0, SOFT_HOURS, 1, 1.0, "softs"),
    "LE=F": _contract("LE=F", "Live cattle", 400.0, LIVESTOCK_HOURS, 3, 0.025, "livestock"),
    "HE=F": _contract("HE=F", "Lean hogs", 400.0, LIVESTOCK_HOURS, 3, 0.025, "livestock"),
}

SPOT_METALS = {
    "XAUUSD=X": ("Gold spot", 2, 0.01),
    "XAGUSD=X": ("Silver spot", 3, 0.001),
    "XPTUSD=X": ("Platinum spot", 2, 0.01),
    "XPDUSD=X": ("Palladium spot", 2, 0.01),
}

# Yahoo has no spot metal quotes (XAUUSD=X answers 404), so a spot metal is
# priced from its front-month COMEX/NYMEX future. The future runs a little above spot.
SPOT_PROXY = {"XAUUSD=X": "GC=F", "XAGUSD=X": "SI=F", "XPTUSD=X": "PL=F", "XPDUSD=X": "PA=F"}

FOREX_PAIRS = [
    ("EURUSD", "Euro / US Dollar"),
    ("GBPUSD", "British Pound / US Dollar"),
    ("USDJPY", "US Dollar / Japanese Yen"),
    ("USDCHF", "US Dollar / Swiss Franc"),
    ("AUDUSD", "Australian Dollar / US Dollar"),
    ("USDCAD", "US Dollar / Canadian Dollar"),
    ("NZDUSD", "New Zealand Dollar / US Dollar"),
    ("EURGBP", "Euro / British Pound"),
    ("EURJPY", "Euro / Japanese Yen"),
    ("EURCHF", "Euro / Swiss Franc"),
    ("EURAUD", "Euro / Australian Dollar"),
    ("EURCAD", "Euro / Canadian Dollar"),
    ("EURNZD", "Euro / New Zealand Dollar"),
    ("GBPJPY", "British Pound / Japanese Yen"),
    ("GBPCHF", "British Pound / Swiss Franc"),
    ("GBPAUD", "British Pound / Australian Dollar"),
    ("GBPCAD", "British Pound / Canadian Dollar"),
    ("GBPNZD", "British Pound / New Zealand Dollar"),
    ("AUDJPY", "Australian Dollar / Japanese Yen"),
    ("AUDNZD", "Australian Dollar / New Zealand Dollar"),
    ("AUDCAD", "Australian Dollar / Canadian Dollar"),
    ("AUDCHF", "Australian Dollar / Swiss Franc"),
    ("NZDJPY", "New Zealand Dollar / Japanese Yen"),
    ("NZDCAD", "New Zealand Dollar / Canadian Dollar"),
    ("CADJPY", "Canadian Dollar / Japanese Yen"),
    ("CADCHF", "Canadian Dollar / Swiss Franc"),
    ("CHFJPY", "Swiss Franc / Japanese Yen"),
    ("USDSEK", "US Dollar / Swedish Krona"),
    ("USDNOK", "US Dollar / Norwegian Krone"),
    ("USDSGD", "US Dollar / Singapore Dollar"),
    ("USDHKD", "US Dollar / Hong Kong Dollar"),
    ("USDMXN", "US Dollar / Mexican Peso"),
    ("USDZAR", "US Dollar / South African Rand"),
    ("USDTRY", "US Dollar / Turkish Lira"),
    ("USDCNH", "US Dollar / Offshore Yuan"),
]

ALIASES = {
    "GOLD": "XAUUSD=X", "XAU": "XAUUSD=X", "XAUUSD": "XAUUSD=X",
    "SILVER": "XAGUSD=X", "XAG": "XAGUSD=X", "XAGUSD": "XAGUSD=X",
    "PLATINUM": "XPTUSD=X", "XPT": "XPTUSD=X", "XPTUSD": "XPTUSD=X",
    "PALLADIUM": "XPDUSD=X", "XPD": "XPDUSD=X", "XPDUSD": "XPDUSD=X",
    "OIL": "CL=F", "WTI": "CL=F", "USOIL": "CL=F", "CRUDE": "CL=F",
    "BRENT": "BZ=F", "UKOIL": "BZ=F",
    "NATGAS": "NG=F", "NATURALGAS": "NG=F",
    "COPPER": "HG=F", "CORN": "ZC=F", "WHEAT": "ZW=F",
    "SOY": "ZS=F", "SOYBEANS": "ZS=F",
    "COFFEE": "KC=F", "COTTON": "CT=F", "SUGAR": "SB=F", "COCOA": "CC=F",
    "CATTLE": "LE=F", "HOGS": "HE=F", "GASOLINE": "RB=F", "HEATINGOIL": "HO=F",
    "MICROGOLD": "MGC=F", "MICROOIL": "MCL=F", "MICROWTI": "MCL=F",
    "MICROSILVER": "SIL=F",
}


def _clean(symbol):
    s = str(symbol or "").strip().upper().replace(" ", "").replace("_", "")
    if "/" in s:
        s = s.replace("/", "")
    if "-" in s and "=" not in s:
        left, _, right = s.partition("-")
        if (left in CURRENCIES or left in METALS) and right in CURRENCIES:
            s = left + right
    return s


def _session_name(session):
    name = str(session or "newyork").strip().lower().replace(" ", "")
    name = SESSION_ALIAS.get(name, name)
    if name not in FOREX_SESSIONS:
        return "newyork"
    return name


def _apply_fx_session(profile, session):
    name = _session_name(session)
    profile.update(FOREX_SESSIONS[name])
    profile["session"] = name
    return profile


def _equity(original):
    return {
        "market": "equity", "symbol": original, "yahoo": original, "name": original,
        "unit": "share", "unit_size": 1, "decimals": 2, "tick": 0.01,
        "point_value": 1.0, "base": None, "quote": "USD", "spot": False,
        "holidays": "nyse", "session": "nyse", "group": "equity",
    }


def _forex(pair, name, session):
    base, quote = pair[:3], pair[3:]
    decimals = 3 if "JPY" in (base, quote) else 5
    profile = {
        "market": "forex", "symbol": pair + "=X", "yahoo": pair + "=X", "name": name,
        "unit": "micro lot", "unit_size": 1000, "decimals": decimals,
        "tick": 10 ** (-decimals), "point_value": None, "base": base, "quote": quote,
        "spot": False, "holidays": "none", "group": "forex",
    }
    return _apply_fx_session(profile, session)


def _spot(yahoo, session):
    name, decimals, tick = SPOT_METALS[yahoo]
    profile = {
        "market": "commodity", "symbol": yahoo, "yahoo": SPOT_PROXY[yahoo], "name": name,
        "unit": "ounce", "unit_size": 1, "decimals": decimals, "tick": tick,
        "point_value": 1.0, "base": yahoo[:3], "quote": "USD", "spot": True,
        "holidays": "none", "group": "spot",
        "data_note": "%s prices come from the %s future (Yahoo has no spot quote); it runs a little above spot"
                     % (yahoo[:6], SPOT_PROXY[yahoo]),
    }
    return _apply_fx_session(profile, session)


def _future(row, session_ignored=None):
    profile = {
        "market": "commodity", "symbol": row["yahoo"], "yahoo": row["yahoo"],
        "name": row["name"], "unit": "contract", "unit_size": 1,
        "decimals": row["decimals"], "tick": row["tick"], "point_value": row["point_value"],
        "base": None, "quote": "USD", "spot": False, "holidays": "cme",
        "group": row["group"], "session": "us",
    }
    profile.update(row["hours"])
    return profile


def classify(symbol, session=None):
    """Symbol, pair, or alias -> a profile. Unknown tickers are equity."""
    original = str(symbol or "").strip().upper()
    cleaned = _clean(original)
    if not cleaned:
        return _equity(original)
    target = ALIASES.get(cleaned, cleaned)
    if target in SPOT_METALS or (target.endswith("=X") and target[:6] in {m + "USD" for m in METALS}):
        yahoo = target if target.endswith("=X") else target + "=X"
        if yahoo in SPOT_METALS:
            return _spot(yahoo, session)
    if target in COMMODITY_TABLE:
        return _future(COMMODITY_TABLE[target])
    if target.endswith("=F"):
        row = COMMODITY_TABLE.get(target)
        if row:
            return _future(row)
        generic = dict(GENERIC_HOURS)
        profile = {
            "market": "commodity", "symbol": target, "yahoo": target,
            "name": target[:-2] + " futures", "unit": "contract", "unit_size": 1,
            "decimals": 2, "tick": 0.01, "point_value": None, "base": None,
            "quote": "USD", "spot": False, "holidays": "cme", "group": "futures",
            "session": "us",
        }
        profile.update(generic)
        return profile
    pair = target[:-2] if target.endswith("=X") else target
    if len(pair) == 6 and pair[:3] in METALS and pair[3:] == "USD":
        yahoo = pair + "=X"
        if yahoo in SPOT_METALS:
            return _spot(yahoo, session)
    if len(pair) == 6 and pair[:3] in CURRENCIES and pair[3:] in CURRENCIES and pair[:3] != pair[3:]:
        known = dict(FOREX_PAIRS).get(pair)
        label = known or ("%s / %s" % (pair[:3], pair[3:]))
        return _forex(pair, label, session)
    return _equity(original)


def is_open_day(profile, day):
    """(open_today, reason). Forex is shut on weekends only. Commodities also shut on CME holidays."""
    if day.weekday() >= 5:
        return False, "weekend"
    if profile.get("holidays") == "cme":
        name = CME_HOLIDAYS.get(day.isoformat())
        if name:
            return False, "CME holiday: " + name
    return True, ""


def session_bounds(profile, day):
    """((open_time, close_time), "") or (None, reason). Equity returns (None, "equity")."""
    if not profile or profile.get("market") == "equity":
        return None, "equity"
    ok, why = is_open_day(profile, day)
    if not ok:
        return None, why
    return (profile["open"], profile["close"]), ""


def adjusted_windows(cfg, profile):
    """(no_entries_before, no_entries_after, flat_by) as HH:MM strings.

    Stock defaults (09:45, 15:30, 15:55) are replaced for forex and commodities.
    A time the user changed on purpose is kept.
    """
    cfg = cfg or {}
    before = str(cfg.get("no_entries_before") or STOCK_BEFORE)
    after = str(cfg.get("no_entries_after") or STOCK_AFTER)
    flat = str(cfg.get("flat_by") or STOCK_FLAT)
    if not profile or profile.get("market") == "equity":
        return before, after, flat
    if before in (STOCK_BEFORE, "9:45"):
        before = profile["no_entries_before"]
    if after in (STOCK_AFTER, "15:30"):
        after = profile["no_entries_after"]
    if flat in (STOCK_FLAT, "15:55"):
        flat = profile["flat_by"]
    return before, after, flat


def _as_time(text):
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(text or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return datetime.time(h, mi)


def window_reasons(now_et, cfg, profile):
    """(reasons, warnings) for one forex or commodity order. Empty reasons means the window is open."""
    if not profile or profile.get("market") == "equity":
        return [], []
    before_s, after_s, _flat = adjusted_windows(cfg, profile)
    before, after = _as_time(before_s), _as_time(after_s)
    d, t = now_et.date(), now_et.time().replace(second=0, microsecond=0)
    stamp = now_et.strftime("%a %Y-%m-%d %H:%M")
    ok, why = is_open_day(profile, d)
    label = profile["market"]
    if not ok:
        return ["window: the %s market is closed today (%s, %s New York)" % (label, why, stamp)], []
    if t < profile["open"] or now_et.time() >= profile["close"]:
        return ["window: the %s session is closed (%s New York; %s to %s)"
                % (label, stamp, profile["open"].strftime("%H:%M"), profile["close"].strftime("%H:%M"))], []
    if before is not None and t < before:
        return ["window: no new entries before %s New York (it is %s)"
                % (before.strftime("%H:%M"), t.strftime("%H:%M"))], []
    if after is not None and t > after:
        return ["window: no new entries after %s New York (it is %s)"
                % (after.strftime("%H:%M"), t.strftime("%H:%M"))], []
    return [], []


def _quote_usd(quote, table):
    if quote == "USD":
        return 1.0
    if isinstance(table, dict) and table.get(quote) not in (None, ""):
        try:
            return float(table[quote])
        except (TypeError, ValueError):
            return None
    return None


def usd_per_point(profile, price, quote_usd=None):
    """USD P&L for a 1.0 move in price, per one sized unit. None if a cross rate is missing."""
    if not profile or profile.get("market") == "equity":
        return 1.0
    if profile.get("market") == "commodity":
        pv = profile.get("point_value")
        return None if pv is None else float(pv)
    units = float(profile.get("unit_size") or 0)
    if profile.get("quote") == "USD":
        return units
    if profile.get("base") == "USD":
        if not price or float(price) <= 0:
            return None
        return units / float(price)
    rate = _quote_usd(profile.get("quote"), quote_usd)
    if rate is None:
        return None
    return units * rate


def notional_per_unit(profile, price, quote_usd=None):
    """USD notional of one sized unit (one micro lot, one contract, one ounce, one share)."""
    if not profile or profile.get("market") == "equity":
        return float(price)
    if profile.get("market") == "commodity":
        pv = profile.get("point_value")
        if pv is None or not price:
            return None
        return float(price) * float(pv)
    units = float(profile.get("unit_size") or 0)
    if profile.get("base") == "USD":
        return units
    if profile.get("quote") == "USD":
        return units * float(price)
    rate = _quote_usd(profile.get("quote"), quote_usd)
    if rate is None or not price:
        return None
    return units * float(price) * rate


def cash_per_unit(profile, price, cfg):
    """Dollars of cash one unit ties up. Full notional unless allow_leverage is on."""
    table = (cfg or {}).get("fx_usd_per_quote")
    notion = notional_per_unit(profile, price, table)
    if notion is None:
        return None
    if (cfg or {}).get("allow_leverage"):
        lev = float((cfg or {}).get("max_leverage") or 1)
        if lev < 1:
            lev = 1.0
        return notion / lev
    return notion


def format_price(profile, x):
    decimals = 2 if not profile or profile.get("market") == "equity" else int(profile.get("decimals") or 2)
    return "%.*f" % (decimals, float(x))


def unit_word(profile, n):
    word = (profile or {}).get("unit") or "share"
    try:
        one = abs(float(n)) == 1
    except (TypeError, ValueError):
        one = False
    if one or word.endswith("s"):
        return word
    return word + "s"


def data_symbol(symbol):
    """The Yahoo symbol to fetch: the spot metal's future for XAUUSD=X and friends, else unchanged."""
    s = str(symbol or "").upper()
    return SPOT_PROXY.get(s, s)


def yahoo_query_symbol(yahoo):
    """Path or query token. Stocks keep BRK.B -> BRK-B. A =X or =F symbol is percent-encoded."""
    y = str(yahoo or "").upper().replace(".", "-")
    if any(c in y for c in "=&"):
        return urllib.parse.quote(y, safe="")
    return y


def universe(market):
    """(symbol, name) rows for scan.py universe --market forex|commodity."""
    kind = "commodity" if str(market).startswith("commod") else str(market)
    if kind == "forex":
        return [(p + "=X", name) for p, name in FOREX_PAIRS]
    if kind == "commodity":
        rows = [(y, name + " (ounce)") for y, (name, _d, _t) in SPOT_METALS.items()]
        for yahoo, row in COMMODITY_TABLE.items():
            rows.append((yahoo, row["name"]))
        return rows
    return []


def suggest_micro(yahoo):
    return MICRO_OF.get(yahoo)


# ---------------------------------------------------------------- TradingView chart links
# A link only: prices still come from Yahoo. TradingView has no public data API.

TRADINGVIEW_CHART = "https://www.tradingview.com/chart/?symbol=%s"
TRADINGVIEW_FUTURES = {
    "GC=F": "COMEX:GC1!", "MGC=F": "COMEX:MGC1!", "SI=F": "COMEX:SI1!", "SIL=F": "COMEX:SIL1!",
    "HG=F": "COMEX:HG1!", "PL=F": "NYMEX:PL1!", "PA=F": "NYMEX:PA1!",
    "CL=F": "NYMEX:CL1!", "MCL=F": "NYMEX:MCL1!", "BZ=F": "NYMEX:BZ1!", "NG=F": "NYMEX:NG1!",
    "HO=F": "NYMEX:HO1!", "RB=F": "NYMEX:RB1!",
    "ZC=F": "CBOT:ZC1!", "ZW=F": "CBOT:ZW1!", "ZS=F": "CBOT:ZS1!",
    "KC=F": "ICEUS:KC1!", "CT=F": "ICEUS:CT1!", "SB=F": "ICEUS:SB1!", "CC=F": "ICEUS:CC1!",
    "LE=F": "CME:LE1!", "HE=F": "CME:HE1!",
}


def tradingview_symbol(symbol):
    """TSLA -> TSLA, BRK-B -> BRK.B, EURUSD=X -> FX_IDC:EURUSD, XAUUSD=X -> OANDA:XAUUSD, CL=F -> NYMEX:CL1!."""
    prof = symbol if isinstance(symbol, dict) else classify(symbol)
    if prof["market"] == "equity":
        return str(prof["symbol"]).upper().replace("-", ".")
    yahoo = prof["yahoo"]
    if prof["market"] == "forex":
        return "FX_IDC:" + yahoo[:-2]
    if prof.get("spot"):
        return "OANDA:" + prof["symbol"][:-2]
    return TRADINGVIEW_FUTURES.get(yahoo) or (yahoo[:-2] + "1!")


def tradingview_url(symbol):
    return TRADINGVIEW_CHART % urllib.parse.quote(tradingview_symbol(symbol), safe="")


# ---------------------------------------------------------------- ForexFactory economic calendar
# The weekly feed ForexFactory publishes for scripts, refreshed through the week.

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
IMPACTS = ("High", "Medium", "Low", "Holiday")
FF_CURRENCY = {"CNH": "CNY"}


def _event_utc(text):
    """ForexFactory's '2026-11-08T17:30:00-05:00' -> naive UTC, or None."""
    try:
        dt = datetime.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def parse_calendar(data):
    """Feed JSON (bytes, text or list) -> events sorted by time, each with a UTC "time" string."""
    import json
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    rows = json.loads(data) if isinstance(data, str) else data
    if not isinstance(rows, list):
        raise ValueError("the calendar is not a list of events")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        when = _event_utc(r.get("date"))
        if when is None:
            continue
        out.append({
            "title": str(r.get("title") or "").strip(),
            "currency": str(r.get("country") or "").strip().upper(),
            "impact": str(r.get("impact") or "").strip().title(),
            "time": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "forecast": str(r.get("forecast") or ""),
            "previous": str(r.get("previous") or ""),
        })
    out.sort(key=lambda e: (e["time"], e["currency"], e["title"]))
    return out


def event_time(event):
    return datetime.datetime.strptime(event["time"], "%Y-%m-%dT%H:%M:%SZ")


def calendar_currencies(symbol):
    """The currencies whose news moves this symbol. Commodities and metals are priced in USD."""
    prof = symbol if isinstance(symbol, dict) else classify(symbol)
    if prof["market"] == "forex":
        return {FF_CURRENCY.get(prof["base"], prof["base"]), FF_CURRENCY.get(prof["quote"], prof["quote"])}
    return {"USD"}


def calendar_for(events, currencies=None, impacts=None):
    """Events for these currencies (None = all) and impacts (None = all). "All" events always match."""
    cur = {c.upper() for c in currencies} if currencies else None
    imp = {i.title() for i in impacts} if impacts else None
    out = []
    for e in events:
        if cur is not None and e["currency"] not in cur and e["currency"] != "ALL":
            continue
        if imp is not None and e["impact"] not in imp:
            continue
        out.append(e)
    return out


def news_blackout(events, now_utc, symbol, minutes=30, impacts=("High",)):
    """Events for this symbol's currencies within +/- minutes of now (naive UTC)."""
    if not minutes or minutes <= 0:
        return []
    span = datetime.timedelta(minutes=float(minutes))
    hits = []
    for e in calendar_for(events, calendar_currencies(symbol), impacts):
        t = event_time(e)
        if t - span <= now_utc <= t + span:
            hits.append(e)
    return hits


def calendar_covers(events, now_utc):
    """True when the saved calendar's week includes now (the feed is one week, Sunday to Saturday)."""
    if not events:
        return False
    first, last = event_time(events[0]), event_time(events[-1])
    return first - datetime.timedelta(days=2) <= now_utc <= last + datetime.timedelta(days=2)
