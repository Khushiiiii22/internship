from datetime import date
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from nse_downloader.db import DatabaseStorage

def test_database_storage_creates_file_and_table(tmp_path):
    db_path = tmp_path / "test.db"
    db_storage = DatabaseStorage(db_path=db_path)
    
    df = pd.DataFrame([{"symbol": "TCS", "ltp": 3500.0}])
    db_storage.save_dataframe(df, "top-gainers", date(2026, 9, 18))
    
    assert db_path.exists()
    
    with sqlite3.connect(db_path) as conn:
        result = pd.read_sql("SELECT * FROM top_gainers", conn)
        
    assert len(result) == 1
    assert result.iloc[0]["symbol"] == "TCS"
    assert result.iloc[0]["fetch_date"] == "2026-09-18"
