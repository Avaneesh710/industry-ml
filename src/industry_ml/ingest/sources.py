"""Where every raw dataset comes from."""
# All URL and Series code in one place so only this file changes when you have a change in the data files

FRENCH_BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"

FRENCH_FILES = {
    "industries": "49_Industry_Portfolios_CSV.zip",
    "ff5": "F-F_Research_Data_5_Factors_2x3_CSV.zip",
    "momentum": "F-F_Momentum_Factor_CSV.zip",
}

FRED_SERIES = {
    "GS10": "10-year Treasury constant maturity yield, % p.a., monthly average",
    "TB3MS": "3-month Treasury bill secondary market rate, % p.a., monthly average",
    "BAA": "Moody's Baa corporate bond yield, % p.a., monthly average",
    "AAA": "Moody's Aaa corporate bond yield, % p.a., monthly average",
    "CPIAUCNS": "CPI-U all items, index 1982-84=100, not seasonally adjusted",
}

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"


def french_url(key: str) -> str:
    return f"{FRENCH_BASE_URL}/{FRENCH_FILES[key]}"