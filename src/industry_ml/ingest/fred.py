"""Download and parse series from the official FRED API.

The API needs a free key (https://fredaccount.stlouisfed.org/apikeys),
read from FRED_API_KEY in .env. The key is never logged or stored.
"""

import json
import os
import urllib.parse
from pathlib import Path

import pandas as pd

from industry_ml.ingest.download import fetch
from industry_ml.ingest.sources import FRED_API_URL

def api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise RuntimeError("FRED_API_KEY is not set. Get a free key at " "https://fredaccount.stlouisfed.org/apikeys and add it to .env")
    return key

def series_url(series_id: str, key: str) -> str:  # urlencode builds query string and escapes any special charaters. strs break when value has & or a space
    query = urllib.parse.urlencode({"series_id": series_id, "api_key": key, "file_type": "json"})
    return f"{FRED_API_URL}?{query}"

def fetch_series(series_id: str, raw_dir: Path, refresh: bool = False) -> Path:
    dest = raw_dir / f"fred_{series_id}.json"  # checks cache before asking for key so key not needed when files are downloaded 
    if dest.exists() and not refresh:
        return dest
    return fetch(series_url(series_id, api_key()), dest, refresh=True, label=f"FRED {series_id}" )

def tidy_series(series_id: str, path: Path) -> pd.DataFrame:
    observations = json.loads(path.read_text())["observations"]
    frame = pd.DataFrame(observations, columns=["date", "value"])
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce") # "." means missing, errors turns to Nan then gets dropped later
    frame["month"] = pd.to_datetime(frame["date"]).dt.to_period("M").dt.to_timestamp() # .dt.to_period("M").dt.to_timestamp() snaps any date to the first of the month
    frame["series_id"] = series_id
    return frame.dropna(subset=["value"])[["series_id", "month", "value"]]


"""
The four interest-rate series:

TB3MS : Yield on 3-month US Treasury bills. A Treasury bill is short-term borrowing by the US government, treated as risk-free because default is effectively ruled out.
GS10  : Yield on 10-year US government bonds
AAA   : Yield on corporate bonds rated Aaa, Moody's highest credit rating (very unlikely to default)
BAA   : Yield on corporate bonds rated Baa, the lowest rating still called "investment grade"
"""

""" 
Present value [PV] = Payment [C] / (1 + y)^t    where  y is the rate of growth per yr , t in yrs , behaves like exp(-λt) where λ = ln(1 + y)

A bond pays a fixed coupon C each year and its face value F (usually 100) at maturity T. 
The market sets its price P. The yield to maturity is the single discount rate y that makes the present value of all those payments equal the price:

   P = {t=1 to T} ∑ C / (1 + y)^t  +  F / (1 + y)^T     (the face value F is paid once, at maturity T)
"""
""" 
    A spread is a difference between two yields:
    Term Spread: GS10 - TB3MS     -  slope of yield curve (plot of yield against bond's maturity). Normalltyy log-term rates are higher so positive.  
    When it is negative the curve is inverted: markets expect interest rates to fall usually when economy weakens
    
    Credit Spread: BAA - AAA      - extra yield investors demand for lending to riskier companies. Jumps when people fear defaults
    
"""

""" 
   CPIAUCNS is the US Consumer Price Index: the price of a fixed basket of goods and services, scaled so the 1982 to 1984 average is 100.
   Monthly inflation is the growth rate of that index, the log version adds up over time:
                     π_t = ln( CPI_t  /  CPI_{t-1})
        
    A prediction made at the end of the month may only us info actually availible at the end of that month, anything else is look-ahead bias, this is what breaks backtests.
    
    CPI breaks this via:
        Publication Lag: CPI for month t published in the middle of month t+1 so and end of month you only know CPI up to month t-1
        Revisons: seasonally adjusted CPI recalc every year so 1995 version isnt what people saw in 1995
        So chose the NS in CPIAUCNS which isnt revised this way.
                     
"""