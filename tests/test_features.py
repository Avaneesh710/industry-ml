"""Checks on the feature panel: structure, an independent re-computation in
pandas, and a direct test that no feature uses information from the future."""

import numpy as np
import pandas as pd
import pytest

from industry_ml.db import get_connection, read_sql

PANEL_QUERY = "SELECT * FROM features.panel WHERE month = %(month)s ORDER BY industry"

# scope="module": the fixture runs once for the whole file, and every test shares the result. The panel is read from the database once, not five times.
@pytest.fixture(scope="module")
def panel():
    return read_sql("SELECT * FROM features.panel ORDER BY industry, month")


@pytest.fixture(scope="module")
def returns():
    return read_sql(
        "SELECT month, industry, ret, ret_excess, mkt_rf "
        "FROM features.industry_returns ORDER BY industry, month"
    )


def pandas_features(returns: pd.DataFrame) -> pd.DataFrame:
    """The rolling features again, written in pandas instead of SQL."""
    pieces = []
    for industry, g in returns.groupby("industry"):
        g = g.set_index("month")
        log_ret = np.log1p(g["ret"])
        f = pd.DataFrame(index=g.index)
        f["mom_12_1"] = np.expm1(log_ret.shift(1).rolling(11).sum())   # shift(1) moves every value down one row, so row t holds t−1's value. 
        f["mom_36_13"] = np.expm1(log_ret.shift(12).rolling(24).sum()) # Combined with rolling, which looks back from the current row:
        f["vol_12"] = g["ret"].rolling(12).std()
        f["beta_60"] = (
            g["ret_excess"].rolling(60).cov(g["mkt_rf"]) / g["mkt_rf"].rolling(60).var()
        )
        f["next_excess"] = g["ret_excess"].shift(-1)
        f["industry"] = industry
        pieces.append(f.reset_index())
    return pd.concat(pieces, ignore_index=True)

# pandas_features computes the same features a second, completely independent way, in pandas instead of SQL. If the two agree to 9 significant figures,
# a bug would have to have been made identically in two different languages, which is very unlikely. 
# It's the same reasoning as checking an analytic result against a numerical simulation.


def fetch(conn, query: str, params: dict) -> pd.DataFrame:
    cur = conn.execute(query, params)
    return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

# fetch runs a query on a connection you pass in, which the last test needs so all its queries happen inside one transaction.

def test_one_row_per_month_and_industry(panel):
    assert not panel.duplicated(["month", "industry"]).any()


def test_no_month_is_missing(panel): # builds every month from the first to the last,  ("MS" means month start) and compares that with the months actually in the panel.
    months = pd.to_datetime(panel.month.drop_duplicates())
    expected = pd.date_range(months.min(), months.max(), freq="MS")
    assert months.tolist() == expected.tolist()


def test_all_49_industries_from_june_1974(panel):
    counts = (
        panel[panel.month >= pd.Timestamp("1974-06-01").date()].groupby("month").size()
    )
    assert (counts == 49).all()


def test_only_the_latest_month_lacks_a_target(panel): #  a missing target anywhere else would mean a gap in the data.
    missing = set(panel.loc[panel.target.isna(), "month"])
    assert missing == {panel.month.max()}

def test_sql_features_match_pandas(panel, returns):
    expected = pandas_features(returns)
    merged = panel.merge(expected, on=["month", "industry"], suffixes=("", "_pd"))
    assert len(merged) == len(panel)
    for column in ["mom_12_1", "mom_36_13", "vol_12", "beta_60"]:
        np.testing.assert_allclose(
            merged[column], merged[f"{column}_pd"], rtol=1e-9, err_msg=column
        )
    has_target = merged.target.notna()
    np.testing.assert_allclose(
        merged.target[has_target], merged.next_excess[has_target], rtol=1e-12
    )

# assert_allclose(a, b, rtol=1e-9) passes if |a - b| ≤ 10⁻⁹ × |b|
# for every element: agreement to about 9 significant figures, which allows for floating-point rounding but nothing else.
# err_msg=column names the failing feature in the error output.

def test_features_do_not_use_the_future():
    """Delete every row after a cutoff month, rebuild the panel, and check that
    the cutoff month's features are unchanged. Only the target may change.
    All of it happens inside a transaction that is rolled back afterwards."""
    cutoff = {"month": "2000-06-01"}
    with get_connection() as conn:
        before = fetch(conn, PANEL_QUERY, cutoff)
        with conn.transaction(force_rollback=True): # opens a transaction that always rolls back at the end, even when everything succeeds: ACID atomicity, used as sandbox
            for table in [ #                          deletes and the refresh happen, the test reads the result, and then the database returns to exactly how it was.
#                                                     Postgres even lets REFRESH MATERIALIZED VIEW happen inside a transaction and be rolled back.
                "raw.industry_monthly",
                "raw.ff5_factors",
                "raw.fred_monthly",
            ]:
                conn.execute(f"DELETE FROM {table} WHERE month > %(month)s", cutoff)
            conn.execute("REFRESH MATERIALIZED VIEW features.panel")
            after = fetch(conn, PANEL_QUERY, cutoff)

    assert len(before) == 49
    pd.testing.assert_frame_equal( # pd.testing.assert_frame_equal compares two whole DataFrames, values and column types, and reports the first difference.
        before.drop(columns="target"), after.drop(columns="target")
    )
    assert before.target.notna().all()
    assert after.target.isna().all()

# This test applies the definition of look-ahead directly: if the future had never happened, would this month's features be any different?
# It deletes every row after June 2000 from the raw tables, rebuilds the panel, and checks that June 2000's features are exactly the same.
# The target must change (it becomes NULL, because July 2000 no longer exists), which proves the deletion really took effect.


