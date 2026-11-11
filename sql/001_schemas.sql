-- Three layers, each in its own schema:
--   raw      : data exactly as downloaded, after parsing only
--   features : model inputs derived from raw (built in SQL)
--   results  : model predictions and backtest outputs
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS features;
CREATE SCHEMA IF NOT EXISTS results;