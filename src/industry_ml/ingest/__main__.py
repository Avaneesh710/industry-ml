"""Download all raw sources and load them into the raw schema.

Usage: python -m industry_ml.ingest [--refresh] [--skip-fred]
"""
#  type python -m industry_ml.ingest. -m runs a module by its import name, so the imports work from any folder.
import argparse
import hashlib
import logging

import pandas as pd

from industry_ml.db import PROJECT_ROOT, get_connection
from industry_ml.ingest import fred, french
from industry_ml.ingest.download import fetch, sha256
from industry_ml.ingest.load import replace_table
from industry_ml.ingest.sources import (
    FRED_API_URL,
    FRED_SERIES,
    FRENCH_FILES,
    french_url,
)
RAW_DIR = PROJECT_ROOT / "data" / "raw"
FRENCH_TARGETS = {                                # dispatch table: a dict whose values include functions (french.tidy_industries, without brackets, is the function itself, not a call).
    "industries": ("raw.industry_monthly", french.tidy_industries), #  One loop then handles all three files, and adding a fourth is one new line in the dict.
    "ff5": ("raw.ff5_factors", french.tidy_monthly_factors),
    "momentum": ("raw.ff_momentum", french.tidy_monthly_factors),
}

def load_french(conn, refresh: bool) -> None:
    for key, (table, tidy) in FRENCH_TARGETS.items():
        url = french_url(key)
        path = fetch(url, RAW_DIR / FRENCH_FILES[key], refresh=refresh)
        text = french.read_zip_text(path)
        frame = tidy(french.parse_sections(text))
        replace_table(conn, table, frame, url, sha256(path), french.parse_vintage(text))
        
def load_fred(conn, refresh) -> None:
    paths = {sid: fred.fetch_series(sid, RAW_DIR, refresh) for sid in FRED_SERIES}
    frame = pd.concat([fred.tidy_series(sid, path) for sid, path in paths.items()]) #The five FRED files are loaded as one table, so their fingerprint is the hash of their five hashes 
    combined_hash = hashlib.sha256("".join(sha256(p) for p in paths.values()).encode()).hexdigest() # joined together. If any one file changes, the combined hash changes.
    source = f"{FRED_API_URL}?series_id={','.join(FRED_SERIES)}"
    replace_table(conn, "raw.fred_monthly", frame, source, combined_hash)

def main():
    parser = argparse.ArgumentParser(description=__doc__) # argparse handles the command-line options. --refresh and --skip-fred become args.refresh and args.skip_fred, --help comes for free.
    parser.add_argument("--refresh", action="store_true", help="re-download cached files")
    parser.add_argument("--skip-fred", action="store_true", help="load Ken French data only")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with get_connection() as conn:        # with get_connection() as conn: closes the connection when the block ends, even if an error occurs.
        load_french(conn, args.refresh)
        if not args.skip_fred:
            load_fred(conn, args.refresh)

if __name__ == '__main__': #  runs main() only when the file is run directly, not when it's imported (for example by a test)
    main()