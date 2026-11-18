"""Data-quality checks on the loaded raw layer. Run after ingestion."""

import pytest

from industry_ml.db import read_sql
from industry_ml.ingest.sources import FRED_SERIES

# Healthcare (Hlth), the last industry to appear, starts in July 1969.
FULL_PANEL_START = "1969-07-01"


def scalar(query: str): # scalar runs a query and returns the single value in its first row and column.
    return read_sql(query).iloc[0, 0]


def test_tables_are_loaded():
    for table in [
        "raw.industry_monthly",
        "raw.ff5_factors",
        "raw.ff_momentum",
        "raw.fred_monthly",
    ]:
        assert scalar(f"SELECT count(*) FROM {table}") > 0, table


def test_49_industries_every_month():
    counts = read_sql(
        "SELECT month, count(*) AS n FROM raw.industry_monthly GROUP BY month HAVING count(*) <> 49"
    )                    # GROUP BY month HAVING count(*) <> 49: GROUP BY makes one group per month, 
    assert counts.empty  # and HAVING keeps only groups whose count isn't 49. WHERE filters rows before grouping, HAVING filters groups after. The test passes when no month comes back.
                         


def test_no_missing_months(): # test_no_missing_months uses a standard SQL pattern for finding gaps,
    gaps = scalar(
        """
        SELECT count(*)
        FROM generate_series(
            (SELECT min(month) FROM raw.industry_monthly),
            (SELECT max(month) FROM raw.industry_monthly),
            interval '1 month'
        ) AS expected(month)
        LEFT JOIN (SELECT DISTINCT month FROM raw.industry_monthly) AS actual USING (month)
        WHERE actual.month IS NULL
        """
    )
    assert gaps == 0
    
""" 
generate_series(start, end, interval '1 month') builds the complete list of months you'd expect. 
A LEFT JOIN keeps every row of that list, attaching the matching row from the data where one exists and NULL where none does. 
WHERE actual.month IS NULL then keeps only the months with no data. This is called an anti-join: "rows in A with no partner in B".

expected.month	 actual.month	            Kept by the WHERE?
2026-07-01	      2026-07-01	                     no
2026-08-01	    NULL (imagine it was missing)	  yes: a gap
2026-09-01	      2026-09-01	                     no

"""

def test_all_industries_present_from_full_panel_start():
    missing = scalar(
        f"SELECT count(*) FROM raw.industry_monthly WHERE month >= '{FULL_PANEL_START}' AND ret_vw IS NULL"
    )
    assert missing == 0
    # July 1969  was the first month where all 49 industries were present and did not change since.
    # First chose July 1963 when Fama-French 5-factor data started but healthcare was not present till June 1969 and software not present till June 1965
    
def test_returns_are_decimals_not_percent():
    median_abs = scalar(
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(ret_vw)) FROM raw.industry_monthly"
    )
    assert 0.01 < median_abs < 0.10
    # The mean uses every value's size, so one huge value can drag it anywhere. 
    # The median uses only the ordering, so it barely moves. Statistics that resist outliers like this are called robust.
    # Paper returned +300% in August 1932, when the industry contained exactly one firm
    # Early portfolios with only one or two firms are very noisy, which is one more reason to start the sample in 1969
    
""" 
For a normal distribution, values more than 3σ from the mean are rare: P(|Z| > 3) ≈ 0.27% ,
and the probability falls off like exp(-z² / 2).
Across all 56,079 industry-months, σ = 7.78% per month. A move of ±30% is 3.86σ, which a Gaussian puts at 0.011% of months. The data has 0.67%: about 60 times more.
"""

def test_cap_weighted_industries_reproduce_the_market():
    """Value-weighting the 49 industries by market cap should rebuild the
    Fama-French market return (Mkt-RF + RF) almost exactly."""
    check = read_sql(
        """
        WITH caps AS (
            SELECT month, ret_vw, n_firms * avg_size AS cap
            FROM raw.industry_monthly
            WHERE ret_vw IS NOT NULL
        ),
        rebuilt AS (
            SELECT month, sum(cap * ret_vw) / sum(cap) AS mkt
            FROM caps
            GROUP BY month
        )
        SELECT corr(r.mkt, f.mkt_rf + f.rf)        AS correlation,
               avg(abs(r.mkt - (f.mkt_rf + f.rf))) AS mean_abs_error
        FROM rebuilt AS r
        JOIN raw.ff5_factors AS f USING (month)
        """
    ).iloc[0]
    assert check.correlation > 0.999
    assert check.mean_abs_error < 0.001

""" 
The centre of mass of masses mᵢ at positions xᵢ is:  ∑ᵢ mᵢxᵢ / ∑ᵢ mᵢ

Replace mass with market capitalisation (the total value of an industry's shares) and position with return, and you get the value-weighted market return:
           ∑ᵢ cap_{i,t}R_{i,t}
 R_{m,t} = -------------------,       cap_{i,t} = n_{i,t} * s_{i,t}
              ∑ᵢ cap_{i,t}
where n_{i,t} is the number of firms and s_{i,t} is the average firm size. Big industries pull the market the way heavy masses pull a centre of mass.

Industry A is worth £300m and returns +2%. Industry B is worth £100m and returns −4%. R_m = 0.5% The equal-weighted average would be (2% − 4%) / 2 = −1%, a different sign. 
The SQL does exactly this sum for each month: the caps CTE computes n * s
for each industry, and sum(cap * ret_vw) / sum(cap) … GROUP BY month is the formula above, term for term.

Why this one test is worth so much: it checks three tables at once.

Units: a percent-versus-decimal mix-up in any of the three would make the gap about 100 times bigger.

Month alignment: monthly returns are almost uncorrelated from one month to the next, close to white noise. 
If either table were shifted by even one month, the correlation would collapse to near zero.

What avg_size means: using the same month's firm size fits better than the previous month's. 
Size is measured at the start of the month, before that month's return happens. 
That matters later where a feature may only use values known before the return it predicts.


"""

def test_risk_free_rate_agrees_with_fred_tbill():
    """FF's 1-month T-bill return should track FRED's 3-month T-bill yield
    converted from % per year to a decimal per month."""
    correlation = scalar(
        """
        SELECT corr(f.rf, t.value / 100 / 12)
        FROM raw.ff5_factors AS f
        JOIN raw.fred_monthly AS t ON t.month = f.month AND t.series_id = 'TB3MS'
        """
    )
    assert correlation == pytest.approx(1, abs=0.02)

""" 
Two independent sources should tell the same story about the risk-free rate: 
Fama-French's 1-month Treasury bill return, and FRED's 3-month Treasury bill yield, converted from percent per year to a decimal per month.
            ∑_t (x_t - x̄)(y_t - ⁻y⁻)     [y_bar]
ρₓᵧ = ----------------------------------- ,     Pearson Correlation  
       √(∑_t (x_t - x̄)²∑_t (y_t - ⁻y⁻)²)

The numerator is the covariance, the denominator the product of the two spreads, so 
ρ always lies between −1 and +1. SQL's corr(a, b) aggregate computes exactly this.

Now multiply every y by 100. Every y - y_bar gets multiplied by 100, the numerator gains a factor of 100, and the denominator gains (100^2)^(0.5)
They cancel, and ρ is still 0.849. Correlation can't see a change of units. 
That's why the market test above also checks the average absolute gap, and why the median test exists. Each test covers another's blind spot.

The real correlation is 0.987, not 1, because the two series aren't quite the same thing: 
1-month versus 3-month bills, a realised return versus a quoted yield, and different data providers. pytest.approx(1, abs=0.02) accepts anything from 0.98 to 1.02.
"""

def test_every_fred_series_loaded():
    loaded = set(
        read_sql("SELECT DISTINCT series_id FROM raw.fred_monthly")["series_id"]
    )
    assert loaded == set(FRED_SERIES)
# Comparing two sets checks that every series in sources.py arrived and nothing unexpected did, regardless of order.