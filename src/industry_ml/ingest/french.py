"""Parsers for Ken French Data Library CSV files.

Each file holds several tables one after another. A table starts with a
header line beginning with a comma (the unnamed date column), is preceded
by a title line, and ends at the first line that does not start with a
digit. Dates are YYYYMM for monthly tables and YYYY for annual ones.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

MISSING_CODES = ["-99.99", "-999"]  # French writes these when there iss no data so pandas will turn these into Nan
PERCENT = 0.01

@dataclass  # generates __init__
class Section:
    title: str
    frame: pd.DataFrame
    
    @property                                     # turns method into smth accessed as attribute (section.is_monthly) computed each time read
    def is_monthly(self):                         # checks if length of date label is 6 digits long YYYYMM instead of YYYY           
        return len(str(self.frame.index[0])) == 6

def read_zip_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:              # zipfile.Zipfile opens archip without unpacking it to disk
        (member,) = archive.namelist()                  # this line is tuple unpacking with a single slot, succeds only if the zip only exactly one file otherwise fails
        return archive.read(member).decode("latin-1")   # turns raw bytes to text with latin-1 mapping evey possible byte to a char so decoding never fails. Files are plain ASCII
    
def parse_vintage(text: str) -> str | None:
    match = re.search(r"created using the (\d{6}) CRSP database", text) # (\d{6}) () is capture group so remembers what was matched and \d{6} is 6 digits of 0-9: 202609 is SEP-2026
    return match.group(1) if match else None                            # Matches None if sentence changes 

# One Ken French file has several tables: this func finds each one and reads it into a dataframe

def parse_sections(text: str) -> list[Section]:
    lines = text.splitlines()
    sections: list[Section] = []
    title = ""
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith(","):                                      # table begins if starts with ","
            end = i + 1
            while end < len(lines) and lines[end].strip()[:1].isdigit():  # if rows start with a digit keep reading and ends when there is a blank space
                end +=1                                                   # [:1] takes first char or empty string for a blank line which would be false so ends the table 
            frame = pd.read_csv(
                io.StringIO("\n".join(lines[i:end])),                     # io.StringIO wraps a str so pd.read_csv can read it as if it were a file
                index_col = 0,                                            # uses first col (dates) as row labels
                skipinitialspace=True,                                    # ignores the spaces after each comma
                na_values=MISSING_CODES, 
            )
            frame.columns = [str(c).strip() for c in frame.columns]
            sections.append(Section(title, frame))
            i = end
            continue
        if stripped:                        
            title = stripped                                           # if no "," at start recognised as title
        i += 1
    return sections 
        
            
def section_by_title(sections: list[Section], title: str) -> Section:
    for section in sections:
        if section.title == title:
            return section
    raise KeyError(f"No section titled {title!r}; found {[s.title for s in sections]}") # keyerror whose message lists every title found if if ever renamed the error will tell the new name.


def first_monthly(sections: list[Section]) -> Section:
    return next(s for s in sections if s.is_monthly)     # (...) generator expression, produces matching sections one at a time on demand. next() takes the first and then stops


def yyyymm_to_month(index: pd.Index) -> pd.DatetimeIndex:
    return pd.to_datetime(index.astype(str), format="%Y%m")  # %Y is 4-digit yr, %m is 2-digit month e.g. 192607 gives 1926-07-01
    

def _monthly_long(section: Section, value_name: str, scale: float = 1.0) -> pd.DataFrame:  # _month... means only used in this file 
    frame = section.frame * scale                   # scales tables, converts dates and melts it
    frame.index = yyyymm_to_month(frame.index)
    return(
        frame.rename_axis("month").reset_index()   # turns date labels into month col as melt needs it as an ordinary col                         
        .melt(id_vars="month", var_name="industry", value_name=value_name)      # turns wide tables (one row per month, one column per industry) 
        # to long tables ( one row per observation, with the industry as a value in a column.) known as tidy data .melt does this
    )
    
def tidy_industries(sections: list[Section]) -> pd.DataFrame:           # reads 4 tables melts each and merges them on (month, industry) into one table with 4 value cols - 
    parts = [
        ("Average Value Weighted Returns -- Monthly", "ret_vw", PERCENT), # Converts both return tables into decimals
        ("Average Equal Weighted Returns -- Monthly", "ret_ew", PERCENT),
        ("Number of Firms in Portfolios", "n_firms", 1.0),
        ("Average Firm Size", "avg_size", 1.0)
    ]
    frames = [
        _monthly_long(section_by_title(sections, title ), name, scale) for title, name, scale in parts 
    ]
    tidy = frames[0]
    for frame in frames[1:]:
        tidy = tidy.merge(frame, on=["month", "industry"], how="outer", validate="1:1") # outer is like outer merge so nothing dropped, 1:1 raises an error if (month, industry) pair appears >1
    tidy["n_firms"] = tidy["n_firms"].astype(int)                                       
    return tidy.sort_values(["month", "industry"]).reset_index(drop=True)
    
    
def tidy_monthly_factors(sections: list[Section]) -> pd.DataFrame:  # converts nsame so sql reds them correctly
    section = first_monthly(sections)
    frame = section.frame * PERCENT
    frame.index = yyyymm_to_month(frame.index)
    frame.columns = [c.lower().replace("-","_") for c in frame.columns]
    return frame.rename_axis("month").reset_index()