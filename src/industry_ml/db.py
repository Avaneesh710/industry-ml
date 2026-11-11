"""Database connection helpers.

Connection settings come from the standard libpq environment variables
(PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE), loaded from .env.
psql and psycopg both read these, so the shell scripts and Python code
always talk to the same database.
"""

from pathlib import Path
import pandas as pd 
import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

def get_connection() -> psycopg.Connection:
    return psycopg.connect()                                       # -> points what type the return val be for notation

def read_sql(query: str, params: dict | None = None) -> pd.DataFrame:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(query, params)                                     # dataframe with all row values and sql column names as columns
        columns = [col.name for col in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=columns)