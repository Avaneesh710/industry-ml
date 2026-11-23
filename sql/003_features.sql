-- Each row of the finished table describes one industry at the end of one month, t:

-- Column	                 What it measures	                                        Months it uses

-- rev_1m	            This month's return	                                                 t
-- mom_12_1	    Momentum: return over the past year, skipping the latest month	       t−11 to t−1
-- mom_36_13	    Long-term past return, 3 years to 1 year ago	                   t−35 to t−12
-- vol_12	        Volatility: how much monthly returns varied over the past year	     t−11 to t
-- beta_60	       Beta: how strongly the industry moves with the market	             t−59 to t
-- log_cap	          Size: log of the industry's total market value	                start of t
-- term_spread	          10-year minus 3-month Treasury yield 	                             t
-- credit_spread	     Baa minus Aaa corporate bond yield      	                         t
-- infl_lag1	   Inflation, lagged because of the publication delay	                    t−1
-- target	     What we'll try to predict: next month's excess return	                    t+1


-- Feature layer. Each row of features.panel describes one industry at the end
-- of month t, using only information available at that moment, plus the
-- target: that industry's excess return in month t+1.
--
-- Views store no data of their own, so this migration drops and recreates
-- them on every run. A changed definition therefore always takes effect.

DROP MATERIALIZED VIEW IF EXISTS features.panel;  -- A view holds no data, so dropping and recreating it loses nothing. 
DROP VIEW IF EXISTS features.industry_features; -- This migration does exactly that on every run, so an edited definition always takes effect.
DROP VIEW IF EXISTS features.macro; -- The drops run in reverse dependency order: panel reads from industry_features and macro, which read from industry_returns
DROP VIEW IF EXISTS features.industry_returns; -- could add CASCADE to drop dependants automatically, but then a drop can remove more than you meant,



-- Three ways to keep a result in a database:

-- Kind:	                    What's stored:	                             When it's computed:	                        Used here for:

-- Table                      the data itself	                          you write rows into it	                         the raw layer
-- View	                  only the query: a named SELECT	           every time someone reads it	                  the three intermediate steps
-- Materialised view	the query and a saved copy of its result	 when created, and on each REFRESH	                   the final panel

-- A view is a recipe and a materialised view is the dish, cooked and kept in the fridge. 
-- Recomputing every rolling window over 59,000 rows on each read would be wasteful 
-- when models will read the panel thousands of times, so the last step is stored. 
-- The price is that it can go stale, which is why the pipeline refreshes it after every ingestion


-- Returns in the forms the features need. LEFT JOIN keeps months before
-- July 1963, when the Fama-French factors (and so rf) begin.
CREATE VIEW features.industry_returns AS
SELECT
    m.month,
    m.industry,
    m.ret_vw                   AS ret,
    ln(1 + m.ret_vw)           AS log_ret, -- ln(1 + m.ret_vw) is the log return which add up over time
    m.ret_vw - f.rf            AS ret_excess, -- excess return: what industry earned above the risk-free Treasury bill rate
    f.mkt_rf,
    ln(m.n_firms * m.avg_size) AS log_cap --  number of firms × average size is the industry's total market value and its log is the size feature. 
--                                            For an empty industry avg_size is NULL, so the result is NULL rather than the error that ln(0) would raise.
FROM raw.industry_monthly AS m
LEFT JOIN raw.ff5_factors AS f USING (month);


-- LEFT JOIN versus JOIN:
-- A plain JOIN (an inner join) keeps only rows that have a partner in both tables. 
-- A LEFT JOIN keeps every row of the left table and fills the right table's columns with NULL where there's no partner.

-- That matters here. The industry table starts in July 1926, but the Fama-French factors only start in July 1963. 
-- An inner join would keep 759 months × 49 industries = 37,191 rows and throw away 37 years of history.
-- Momentum in 1964 needs returns from 1963 and before, so those early rows must survive. 
-- The LEFT JOIN keeps all 58,947 rows, with rf, ret_excess and mkt_rf NULL before July 1963.

-- With logs equal ratios become equal differences

-- Rolling features per industry. Each CASE returns NULL unless the window
-- holds its full number of non-missing months, because aggregates silently
-- skip NULLs and would otherwise average over a shorter history.
CREATE VIEW features.industry_features AS
SELECT
    month,
    industry,
    ret                                                      AS rev_1m,
    CASE WHEN count(log_ret) OVER mom_12_1 = 11
         THEN exp(sum(log_ret) OVER mom_12_1) - 1 END        AS mom_12_1,
    CASE WHEN count(log_ret) OVER mom_36_13 = 24
         THEN exp(sum(log_ret) OVER mom_36_13) - 1 END       AS mom_36_13,
    CASE WHEN count(ret) OVER last_12 = 12
         THEN stddev_samp(ret) OVER last_12 END              AS vol_12,
    CASE WHEN regr_count(ret_excess, mkt_rf) OVER last_60 = 60
         THEN regr_slope(ret_excess, mkt_rf) OVER last_60 END AS beta_60,
    log_cap,
    -- The target is computed here, before any rows are filtered out, so that
    -- "next row" always means "next month".
    lead(ret_excess) OVER by_month                           AS target -- lead(ret_excess) OVER by_month reads the next row's excess return within the same industry: 
FROM features.industry_returns --                                         next month's, because rows are one per month. That's the target. 
    by_month AS (PARTITION BY industry ORDER BY month), --      It deliberately uses the future, because it's the answer the model will be trained to predict, and it's never used as an input.
WINDOW 
    mom_12_1  AS (by_month ROWS BETWEEN 11 PRECEDING AND 1 PRECEDING),
    mom_36_13 AS (by_month ROWS BETWEEN 35 PRECEDING AND 12 PRECEDING),
    last_12   AS (by_month ROWS BETWEEN 11 PRECEDING AND CURRENT ROW),
    last_60   AS (by_month ROWS BETWEEN 59 PRECEDING AND CURRENT ROW);

-- GROUP BY collapses rows: 49 rows for one month become one row of averages.
--  A window function computes an aggregate over a set of related rows but keeps every row, attaching the result to it. The OVER (…) clause says which rows to look at:

-- PARTITION BY industry: split the table into 49 separate groups, one per industry. Windows never cross from Food into Beer.
-- ORDER BY month: within each industry, put the rows in time order.
-- ROWS BETWEEN 11 PRECEDING AND 1 PRECEDING: the frame, the rows the aggregate sees, counted relative to the current row.

-- The WINDOW clause at the bottom names each window once, so it can be reused (OVER mom_12_1 appears twice).
--  mom_12_1 AS (by_month ROWS …) builds on by_month, so the partition and order are written only once.
-- ROWS counts rows, not months. That's only correct because each industry has exactly one row per month with no gaps,

-- SQL evaluates a query in a fixed logical order: FROM → WHERE → GROUP BY → HAVING → window functions → SELECT → ORDER BY. '
-- So lead only sees rows that survived the WHERE. If the panel's WHERE removed February for some industry and lead were computed there, 
-- January's "next month" would silently become March.
--That's why the target is computed in this view, which has no WHERE, and only filtered afterwards in the panel.


-- Products become Sums:
-- Compounding multiples: 1 + R_total = ∐ᵢ(1 + Rᵢ) [(1 + R_1)(1 + R_2)... ] 
-- SQL has sum but no product aggregate. Taking logs turns the product into a sum, and exp turns it back:
--   R_total = exp(∑ᵢln(1+Rᵢ)) - 1 , That's exp(sum(log_ret) OVER mom_12_1) - 1, term for term.

-- Momentum and Reversal Effects
-- Researchers have found that past returns help predict future returns, in ways that depend on the horizon:

-- Momentum (roughly 1 year): assets that rose most over the past year tend to keep outperforming for a while. 
-- For individual stocks the latest month is skipped because it tends to reverse instead, hence "12-1" (12 months back, skipping 1).

-- Industries behave differently at one month. Moskowitz and Grinblatt's study of industry portfolios found that, unlike for individual stocks, 
-- "industry momentum is strongest in the short-term (at the one-month horizon)" (Journal of Finance, 1999). 
-- The feature is still called rev_1m, after the stock-market convention; a model learns from the data which way it points.

-- Long-term reversal (3 to 5 years): past long-run losers tend to do slightly better later. mom_36_13 captures that horizon, ending a year back so it doesn't overlap mom_12_1.
-- Whether these effects still hold in your data, after costs, is what Steps 5 to 7 test. 3.10 has a first rough look.


-- Volatility:  sample standard deviation, and the square root of time: s = √((n - 1)⁻¹ ∑ⁿᵢ₌₁(xᵢ - x̄)²)
-- The n - 1 (Bessel's correction) makes s² an unbiased estimate of the variance, because x̄ is itself estimated from the same data. stddev_samp uses n - 1; std_dev uses n.
-- pandas' .std() also uses n -1
-- To annualise, recall the random walk (diffusion): if the 12 monthly returns are independent, each with variance σ², their sum has variance 12σ².
-- Yearly volatility is σ√12 the same √t growth as the spread of a diffusing particle.


-- An industry's beta measures how strongly it moves with the whole market. A beta of 1.5 means that when the market's excess return is +1%, the industry's tends to be +1.5%.
-- Beta is the slope of a straight-line fit of the industry's excess return (y) against the market's (x), over the past 60 months.


-- The Least Squares Slope: Fitting y = a + bx by least squares gives
--          ∑_t (x_t - x̄)(y_t - ⁻y⁻)     [y_bar]    cov(x,y)
--  b^ =    ------------------------- ,          = ----------
--                ∑_t (x_t - x̄)²                     var(x)

-- SQL computes it directly with regr_slope(y, x). Note the order: y first. Swapping the arguments gives a different and wrong number, and nothing warns you.
-- regr_count(y, x) counts rows where both are non-NULL, which guards the 60-month window.




-- Macro features: one row per month, shared by every industry.
CREATE VIEW features.macro AS
WITH wide AS (
    SELECT
        month,
        max(value) FILTER (WHERE series_id = 'GS10')     AS gs10,
        max(value) FILTER (WHERE series_id = 'TB3MS')    AS tb3ms,
        max(value) FILTER (WHERE series_id = 'BAA')      AS baa,
        max(value) FILTER (WHERE series_id = 'AAA')      AS aaa,
        max(value) FILTER (WHERE series_id = 'CPIAUCNS') AS cpi
    FROM raw.fred_monthly
    GROUP BY month
), --  WITH wide AS (…), inflation AS (…), … chains several CTEs. Each can read the ones before it, so a complicated query reads top to bottom as a series of small steps.
                                                                         
inflation AS (  -- lag(cpi) OVER (ORDER BY month) is the previous month's CPI. With no PARTITION BY, the whole table is one partition, which is right here: there's one row per month.
    SELECT *, ln(cpi / lag(cpi) OVER (ORDER BY month)) AS infl -- ln(cpi / lag(cpi)) is monthly log inflation, 
    FROM wide
),
-- Carry the last known inflation figure forward across gaps. October 2025
-- has no CPI at all: the US government shutdown stopped data collection.
-- count() skips NULLs, so it stays constant through a gap, putting each
-- missing month in the same group as the last month that had a value.
grouped AS (
    SELECT *, count(infl) OVER (ORDER BY month) AS infl_group
    FROM inflation
),
filled AS (
    SELECT *, first_value(infl) OVER (PARTITION BY infl_group ORDER BY month) AS infl_filled
    FROM grouped
)
SELECT
    month,
    gs10 - tb3ms                           AS term_spread,
    baa - aaa                              AS credit_spread,
    -- CPI for month t is published in the middle of month t+1, so at the end
    -- of month t the latest known inflation figure is for month t-1.
    lag(infl_filled) OVER (ORDER BY month) AS infl_lag1
FROM filled;

-- FRED stored in long format, one row per (series, month). To subtract one yield from another, the series must sit side by side as columns.
-- max(value) FILTER (WHERE series_id = 'GS10') means "among this month's rows, take the value of the GS10 row".
-- GROUP BY month collapses each month's five rows into one. Each (series, month) pair has exactly one row (the primary key guarantees it),
-- so max just picks that single value; any aggregate would do.

-- Panel silently lost two months: November and December 2025. The cause was in the data: FRED has no CPI for October 2025.
-- During the US government shutdown of October to November 2025, data collection stopped, and the Bureau of Labor Statistics never published an October 2025 index.
-- Without it, inflation for October and November 2025 can't be computed, and the panel's WHERE … infl_lag1 IS NOT NULL dropped the affected rows.


-- What did an investor actually know at the end of November 2025? The September CPI had been published (late, on 24 October), and no October figure was ever coming.
-- So the latest known monthly inflation was September's. The honest fix is to carry that value forward until a new one exists; 
-- filling the gap with a value computed later would use information nobody had at the time.

-- SQL has no built-in "fill forward" in Postgres, so the view uses a standard trick. count(infl) OVER (ORDER BY month) is a running count of non-NULL values.
-- It goes up by one each normal month and stays flat through a gap, so a gap shares a group number with the last month before it. first_value(…) OVER (PARTITION BY infl_group …) 
-- then gives every month in a group that group's first, real value:

-- month	CPI	        infl	infl_group	infl_filled
-- 2025-09	324.800	  0.00254	k	     0.00254
-- 2025-10	missing	    NULL	k	     0.00254
-- 2025-11	324.122	    NULL	k	     0.00254
-- 2025-12	324.054	  −0.00021	k + 1	−0.00021
-- November's inflation is NULL too, because it needs October's CPI as its starting point. The final lag(infl_filled) then shifts everything by a month for the publication delay,
-- so the panel's rows for October, November and December 2025 all carry September's figure. That matches what was known at the time.
-- If using a value that had not yet released at the time it would be look-ahead bias



-- The model-ready panel, stored on disk so models can read it quickly.
-- Starts in July 1969, the first month with all 49 industries 
-- The target is NULL in the latest month: that row is the live prediction.
CREATE MATERIALIZED VIEW features.panel AS -- CREATE MATERIALIZED VIEW … AS SELECT … runs the query once and stores the result 
SELECT
    i.month,
    i.industry,
    i.rev_1m,
    i.mom_12_1,
    i.mom_36_13,
    i.vol_12,
    i.beta_60,
    i.log_cap,
    m.term_spread,
    m.credit_spread,
    m.infl_lag1,
    i.target
FROM features.industry_features AS i
JOIN features.macro AS m USING (month) -- attaches the month's macro values to all 49 industry rows. An inner join is right here: a month without macro data couldn't be used anyway.
WHERE i.month >= DATE '1969-07-01' --  keeps rows from July 1969 that have every feature. Rows missing the target are kept on purpose: 
  AND i.mom_12_1 IS NOT NULL --        that's the latest month, the live prediction a model would actually be asked to make.
  AND i.rev_1m IS NOT NULL
  AND i.mom_36_13 IS NOT NULL
  AND i.vol_12 IS NOT NULL
  AND i.beta_60 IS NOT NULL
  AND m.term_spread IS NOT NULL
  AND m.credit_spread IS NOT NULL
  AND m.infl_lag1 IS NOT NULL;

-- A unique index guarantees one row per (month, industry) and lets the panel
-- be refreshed without blocking readers (REFRESH ... CONCURRENTLY).
CREATE UNIQUE INDEX panel_month_industry_idx ON features.panel (month, industry);
-- A materialised view can't have a primary key, so a UNIQUE INDEX does the same job: it guarantees one row per (month, industry) and makes lookups fast.

-- Data indexed by both entity and time is a panel. It's balanced if every entity appears in every period. Ours isn't, at the start, because each feature needs enough history.