import sqlite3
from unittest.mock import patch

import pytest


@pytest.fixture
def pending_download_jobs():
    """Persist the jobs whose creation is stubbed by download unit tests."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE transfer_jobs (
               id INTEGER PRIMARY KEY,
               status TEXT,
               provider TEXT DEFAULT '',
               stage TEXT DEFAULT '',
               message TEXT DEFAULT '',
               finished_at TEXT,
               external_provider_status TEXT DEFAULT '',
               save_path TEXT DEFAULT ''
           )"""
    )
    connection.executemany(
        "INSERT INTO transfer_jobs (id,status) VALUES (?, 'running')",
        [(i,) for i in (1, 7, 8, 9, 10, 11, 42)],
    )
    connection.commit()
    try:
        with patch("app.services.direct_link_transfer.db", return_value=connection):
            yield connection
    finally:
        connection.close()
