""" 
There are two kinds of test, in two files.

Unit tests check one piece of code against a tiny input whose correct output you know. They need no network and no database, and run in milliseconds.
Data tests query the loaded database and check facts that must be true of the real data. They catch problems in the data itself, which no unit test can.
"""

import pandas as pd
import pytest

from industry_ml.ingest import french
#SAMPLE is a miniature Ken French file written by hand, with the awkward cases built in:
# the trailing space in "Food ", missing codes, an annual table to skip, and an industry with zero firms.
SAMPLE = """This file was created using the 202609 CRSP database.
Missing data are indicated by -99.99 or -999.


  Average Value Weighted Returns -- Monthly
,Agric,Food ,Soda
192607,   2.36,   0.09, -99.99
192608,   2.23,   2.71, -99.99


  Average Equal Weighted Returns -- Monthly
,Agric,Food,Soda
192607,   1.00,   2.00, -99.99
192608,   3.00,   4.00, -99.99


  Average Value Weighted Returns -- Annual
,Agric,Food,Soda
  1927,  10.00,  20.00, -99.99


  Number of Firms in Portfolios
,Agric,Food,Soda
192607,      5,     20,      0
192608,      5,     21,      0


  Average Firm Size
,Agric,Food,Soda
192607,  10.50,  30.25, -99.99
192608,  10.75,  31.00, -99.99

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""
# @pytest.fixture: any test that names sections as an argument automatically receives the parsed sample. The setup is written once and shared.

@pytest.fixture
def sections():
    return french.parse_sections(SAMPLE)


def test_finds_every_table(sections):
    assert len(sections) == 5
    assert [s.is_monthly for s in sections] == [True, True, False, True, True]


def test_vintage():
    assert french.parse_vintage(SAMPLE) == "202609"


def test_header_whitespace_is_stripped(sections):
    assert list(sections[0].frame.columns) == ["Agric", "Food", "Soda"]

# pytest.approx compares floats with a small tolerance. Floating-point arithmetic is rarely exact:
# in Python, 0.57 * 0.01 gives 0.005699999999999999, so testing it with == 0.0057 would fail even though nothing is wrong.

def test_tidy_industries_units_and_missing(sections):
    tidy = french.tidy_industries(sections)
    assert len(tidy) == 2 * 3
    first = tidy[(tidy.month == "1926-07-01") & (tidy.industry == "Agric")].iloc[0]
    assert first.ret_vw == pytest.approx(0.0236) 
    assert first.n_firms == 5
    soda = tidy[tidy.industry == "Soda"]
    assert soda.ret_vw.isna().all() and (soda.n_firms == 0).all()


def test_month_conversion():
    months = french.yyyymm_to_month(pd.Index([192607, 202612]))
    assert list(months) == [pd.Timestamp("1926-07-01"), pd.Timestamp("2026-12-01")]
    
#Each test's name says what behaviour it protects. When one fails in six months, the name tells you what broke before you've read any code.