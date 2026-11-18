
-- Raw layer: one table per source,
-- values exact apart from unit conversion (% to dec) and missing codes (-99.99 to NULL)
-- Months stored as first day of month described 

CREATE TABLE IF NOT EXISTS raw.load_log (                             -- records every load of data gives data lineage (source, its release date, fingerprint of file and row count)
    load_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,         -- GENERATED ALWAYS AS IDENTITY is modern way of SERIAL new standard
    table_name  text    NOT NULL,
    source_url text     NOT NULL,
    vintage text,
    file_sha256 text NOT NULL,
    row_count integer NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()                    -- timestamptz stores exact moment with () time zones which timestamp doesnt so can cause bugs, 
);                                                                  -- DEFAULT now() is when row inserted with value for this col so uses current time as default

-- Ken French 49 industry portfolios: one row per month,industry
-- decimal returns upper bound of 5 far above any real monthly value but catches forgotten % to dec conversion

CREATE TABLE IF NOT EXISTS  raw.industry_monthly (
    month date NOT NULL CHECK (extract(day FROM month) = 1),  -- only first of the month is used for simplicity
    industry text NOT NULL,
    ret_vw double precision CHECK (ret_vw > -1 AND ret_vw < 5),  -- ret_vw is the value-weighted returns and ret_ew is the equal-weighted returns as decimals
    ret_ew double precision CHECK (ret_ew > -1 AND ret_ew < 5),    
    n_firms integer NOT NULL CHECK (n_firms >= 0),
    avg_size double precision CHECK (avg_size > 0), -- n_firms is no. of firms the industry had that month and avg_size is avg market value in $ millions
    PRIMARY KEY (month, industry),                  -- industry has return when it has at least one firm , each month-industry pair appears once 
    CHECK ((n_firms = 0) = (ret_vw IS NULL))        -- checkes if industry with no firms has no return and vicer versa 
);

-- primary key index serves "all industries in month t" queries 
-- Time series queries per industry want cols other way around

CREATE INDEX IF NOT EXISTS industry_monthly_industry_month_idx ON raw.industry_monthly (industry, month); -- columns reversed so the way it is sorted also changes:
-- 2004-01 Aero, 2004-01 Ag ... 2004-01 Food ---> 2004-01 Aero, 2004-02 Aero, ... 2004-01 Ag, ... 2004-01 Food
-- index is sorted copy of some cols with pointer to each full row, without it would need to search the whole table 

CREATE TABLE IF NOT EXISTS raw.ff5_factors (
    month date PRIMARY KEY CHECK (extract(day FROM month) = 1),
    mkt_rf double precision NOT NULL,                           -- Market excess return --> whole US stock market minus the risk-free rate
    smb double precision NOT NULL,                              -- small minus big -->  Small firm returns - large firms
    hml double precision NOT NULL,                              -- high minus low --> Cheap value stocks (high book-to-market ratio) - expensive "growth" stocks
    rmw double precision NOT NULL,                              -- robust minus weak --> Highly profitable firms - unprofitable ones
    cma double precision NOT NULL,                              -- Conservative minus aggressive --> Firms investing little - firms investing heavily
    rf double precision NOT NULL                                -- risk free rate --> return on 1-month US Treasury bill
);
-- double precision faster than numeric and uses same 64 bit float gives to 16 sig fig while numeric does it exact so is slower
CREATE TABLE IF NOT EXISTS raw.ff_momentum (
    month date PRIMARY KEY CHECK (extract(day FROM month) = 1), 
    mom double precision NOT NULL                               -- Momentum --> Stocks that rose most over the past year - those that fell the most 
);  

-- FRED series in long format, values in the published units (% per yr for yields, index level for CPI) with single value col, one row per series,month rather than one col per series

CREATE TABLE IF NOT EXISTS raw.fred_monthly (
    series_id text NOT NULL,
    month date NOT NULL CHECK (extract(day FROM month) = 1),
    value double precision NOT NULL,
    PRIMARY KEY (series_id, month)          -- tidy format one row per series-month

);