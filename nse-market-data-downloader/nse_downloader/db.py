import logging
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

class DatabaseStorage:
    """Handles storing market data into an SQLite database for historical management."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        # Ensure the directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def save_dataframe(self, df: pd.DataFrame, dataset_name: str, fetch_date: date) -> None:
        """
        Save the DataFrame to the SQLite database.
        Appends the data with a fetch_date column for historical tracking.
        """
        # Create a copy so we don't modify the caller's DataFrame
        df_to_save = df.copy()
        
        # Add the fetch date for historical partitioning
        df_to_save['fetch_date'] = fetch_date.isoformat()

        table_name = dataset_name.replace('-', '_')

        try:
            with sqlite3.connect(self.db_path) as conn:
                df_to_save.to_sql(
                    name=table_name,
                    con=conn,
                    if_exists="append",
                    index=False
                )
            logger.info("Saved %d records to database table '%s'", len(df_to_save), table_name)
        except Exception as exc:
            logger.error("Failed to save to database: %s", exc)
            raise
