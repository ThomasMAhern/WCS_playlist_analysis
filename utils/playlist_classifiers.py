"""Utilities for extracting calendar dates and BPM ranges from playlist names."""

import polars as pl

###########################################################
# Patterns for detecting calendar dates in playlist names #
###########################################################

pattern_yyyy_mm_dd = r'\b(?:19|20)\d{2}[-/.](?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01])\b'
pattern_yyyy_dd_mm = r'\b(?:19|20)\d{2}[-/.](?:0[1-9]|[12]\d|3[01])[-/.](?:0[1-9]|1[0-2])\b'
pattern_dd_mm_yyyy = r'\b(?:0[1-9]|[12]\d|3[01])[-/.](?:0[1-9]|1[0-2])[-/.](?:19|20)\d{2}\b'
pattern_mm_dd_yyyy = r'\b(?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01])[-/.](?:19|20)\d{2}\b'

pattern_yy_mm_dd = r'\b\d{2}[-/.](?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01])\b'
pattern_yy_dd_mm = r'\b\d{2}[-/.](?:0[1-9]|[12]\d|3[01])[-/.](?:0[1-9]|1[0-2])\b'
pattern_dd_mm_yy = r'\b(?:0[1-9]|[12]\d|3[01])[-/.](?:0[1-9]|1[0-2])[-/.]\d{2}\b'
pattern_mm_dd_yy = r'\b(?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01])[-/.]\d{2}\b'

pattern_dd_MMM_yyyy = r'\b(?:0[1-9]|[12]\d|3[01])[-/. ]?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-/. ]?(?:19|20)\d{2}\b'
pattern_MMM_dd_yyyy = r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-/. ]?(?:0[1-9]|[12]\d|3[01])[-/. ]?(?:19|20)\d{2}\b'
pattern_yyyy_MMM_dd = r'\b(?:19|20)\d{2}[-/. ]?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-/. ]?(?:0[1-9]|[12]\d|3[01])\b'
pattern_yyyy_dd_MMM = r'\b(?:19|20)\d{2}[-/. ]?(?:0[1-9]|[12]\d|3[01])[-/. ]?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b'

pattern_dd_MMM_yy = r'\b(?:0[1-9]|[12]\d|3[01])[-/. ]?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-/. ]?\d{2}\b'
pattern_MMM_dd_yy = r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-/. ]?(?:0[1-9]|[12]\d|3[01])[-/. ]?\d{2}\b'
pattern_yy_MMM_dd = r'\b\d{2}[-/. ]?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-/. ]?(?:0[1-9]|[12]\d|3[01])\b'
pattern_yy_dd_MMM = r'\b\d{2}[-/. ]?(?:0[1-9]|[12]\d|3[01])[-/. ]?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b'

pattern_mm_yy = r'\b(?:0[1-9]|1[0-2])[-/. ]\d{2}\b'
pattern_dd_mm = r'\b(?:0[1-9]|[12]\d|3[01])[-/. ](?:0[1-9]|1[0-2])\b'
pattern_yy_mm = r'\b\d{2}[-/. ](?:0[1-9]|1[0-2])\b'
pattern_mm_dd = r'\b(?:0[1-9]|1[0-2])[-/. ](?:0[1-9]|[12]\d|3[01])\b'

pattern_month_year_or_reversed = r"\b(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}|\d{4} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*)\b"

def extract_dates_from_name(playlist_name: pl.Expr, *, sort: bool = False):
    """"Extract a list of calendar dates from the given playlist name."""
    result = pl.concat_list(
        playlist_name.str.extract_all(pattern_yyyy_mm_dd),
        playlist_name.str.extract_all(pattern_yyyy_dd_mm),
        playlist_name.str.extract_all(pattern_dd_mm_yyyy),
        playlist_name.str.extract_all(pattern_mm_dd_yyyy),

        playlist_name.str.extract_all(pattern_yy_mm_dd),
        playlist_name.str.extract_all(pattern_yy_dd_mm),
        playlist_name.str.extract_all(pattern_dd_mm_yy),
        playlist_name.str.extract_all(pattern_mm_dd_yy),

        playlist_name.str.extract_all(pattern_dd_MMM_yyyy),
        playlist_name.str.extract_all(pattern_MMM_dd_yyyy),
        playlist_name.str.extract_all(pattern_yyyy_MMM_dd),
        playlist_name.str.extract_all(pattern_yyyy_dd_MMM),

        playlist_name.str.extract_all(pattern_dd_MMM_yy),
        playlist_name.str.extract_all(pattern_yy_MMM_dd),
        # playlist_name.str.extract_all(pattern_MMM_dd_yy), #matches on Jul 2024 as a date :(
        # playlist_name.str.extract_all(pattern_yy_dd_MMM),  #matches on 2024 Jul as a date :(

        # playlist_name.str.extract_all(pattern_mm_yy),
        # playlist_name.str.extract_all(pattern_dd_mm),
        # playlist_name.str.extract_all(pattern_yy_mm),
        # playlist_name.str.extract_all(pattern_mm_dd),
    ).list.unique()

    return result.list.sort() if sort else result

#######################################################
# Patterns for detecting BPM ranges in playlist names #
#######################################################

pattern_bpm_range = r'(\d{2,3})\s*[-–]\s*(\d{2,3})\s*(?:bpm|BPM)?' # 70 – 79bpm
pattern_bpm_appx = r'[~≈]\s*(\d{2,3})\s*(?:bpm|BPM)?'  # ~100bpm
pattern_bpm_relational = r'[<>]=?\s*(\d{2,3})\s*(?:bpm|BPM)?'  # >120 BPM
pattern_bpm_mention = r'(?:bpm|BPM)[^\d]{0,5}(\d{2,3})'  # bpm 105
pattern_bpm_loose_fallback = r'\b(\d{2,3})\s*(?:bpm|BPM)\b'  # 117 BPM”

def extract_bpm_from_name(playlist_name: pl.Expr):
    """"Extract a list of possible BPM specifications from the given playlist name."""
    raise NotImplementedError()
