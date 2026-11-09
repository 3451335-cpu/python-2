"""Run the same model-based HTTP tests with SQLite storage."""

from src.sqlite_storage import SQLiteStorage

from . import test_api


class SQLiteApiModel(test_api.ApiModel):
    storage_type = SQLiteStorage


TestSQLiteApi = SQLiteApiModel.TestCase
TestSQLiteApi.settings = test_api.TestFileApi.settings
