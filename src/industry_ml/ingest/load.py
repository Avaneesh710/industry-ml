"""Replace a raw table's contents atomically and record the load."""

import logging

import pandas as pd
import psycopg                    # converts vals to plain python that psycog knows to read
from psycopg import sql

log = logging.getLogger(__name__)

def _python_rows(frame: pd.DataFrame):
    converted = frame.copy()
    for col in converted.columns:
        if pd.api.types.is_datetime64_any_dtype(converted[col]):   # datetime64 timestamp  to 	datetime.date	 sql: date
            converted[col] = converted[col].dt.date  # NumPy int64 / float64  to 	Python int / float	 sql: integer / double precision
    converted = converted.astype(object).where(converted.notna(), None)        # Nan converted to None same as sql NULL
    return converted.itertuples(index=False, name=None)                 # itertuples(index=False, name=None) yields each row as a plain tuple, the fastest way to iterate over a DataFrame.

def replace_table(conn: psycopg.Connection, table: str, frame: pd.DataFrame, source_url: str, file_sha256: str, vintage: str | None = None,) -> int:
    schema, name = table.split(".")
    target = sql.Identifier(schema, name) # sql.Identifier quotes table and column names safely, the Python version of %I from init_db.sh
    columns = sql.SQL(", ").join(sql.Identifier(c) for c in frame.columns)
    
    with conn.transaction():
        conn.execute(sql.SQL("DELETE FROM {}").format(target))
        with conn.cursor() as cur:
            copy_stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(target, columns) # COPY … FROM STDIN is Postgres's bulk-loading protocol:
            with cur.copy(copy_stmt) as copy:                                      #  rows stream into the table in one operation instead of 58,947 separate INSERT statements, each waiting for the server's reply
                for row in _python_rows(frame):
                    copy.write_row(row)
        conn.execute(
            "INSERT INTO raw.load_log (table_name, source_url, vintage, file_sha256, row_count )"
            "VALUES (%s, %s, %s, %s, %s)", # Values go through %s placeholders in the log INSERT, never by building the SQL text yourself, which closes the door to SQL injection.
            (table, source_url, vintage, file_sha256, len(frame)),
        )
    log.info("Loaded %d rows into %s", len(frame), table)
    return len(frame)
#  function deletes a table's contents, bulk-loads the new rows, and writes a log entry, all inside with conn.transaction()
""" 
Databases promise four properties for transactions, remembered as ACID. Here's what each means for this pipeline:

Property	Meaning	                                            Here
Atomicity	all of it happens or none of it	                    no half-loaded tables
Consistency	every constraint holds after each transaction	    the CHECKs from 002_raw_tables.sql can't be bypassed
Isolation	others don't see unfinished changes	                a notebook querying during a load sees the old data
Durability	once committed, it survives a crash	                a power cut after COMMIT loses nothing
"""
# Why delete everything and reload? The raw layer mirrors one release of the source. 
# When Ken French revises past months, a full reload is simpler and safer than working out which rows changed.