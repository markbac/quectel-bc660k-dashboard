"""SQLite persistence for signal history."""
import os
import sqlite3
import sys
import time
from contextlib import closing
from typing import Any, Callable, Dict, List, Optional

APP_DIR_NAME = "quectel-bc660k-dashboard"
DB_FILE_NAME = "telemetry.db"
DB_ENV_VAR = "QUECTEL_DASHBOARD_DB"


def default_db_path() -> str:
    """Return the default database location, outside the source tree.

    ``$QUECTEL_DASHBOARD_DB`` wins if set. Otherwise the per-user data
    directory is used (``%LOCALAPPDATA%`` on Windows, ``~/Library/Application
    Support`` on macOS, ``$XDG_DATA_HOME`` or ``~/.local/share`` elsewhere).
    """
    override = os.environ.get(DB_ENV_VAR)
    if override:
        return override
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_DIR_NAME, DB_FILE_NAME)


class SchemaTooNewError(RuntimeError):
    """The database was written by a newer version of the dashboard."""


def _migration_1_create_history(conn: sqlite3.Connection) -> None:
    """Version 1: the original ``signal_history`` table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            unix_time REAL,
            rssi INTEGER,
            csq INTEGER,
            rsrp INTEGER,
            rsrq INTEGER,
            sinr INTEGER,
            ber INTEGER,
            quality_label TEXT,
            operator TEXT,
            mcc TEXT,
            mnc TEXT,
            cell_id TEXT,
            pci INTEGER,
            earfcn INTEGER,
            band TEXT,
            tac TEXT,
            ip_address TEXT,
            voltage INTEGER,
            temperature REAL,
            iccid TEXT,
            imsi TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_unix_time ON signal_history(unix_time)")


def _migration_2_iccid_index(conn: sqlite3.Connection) -> None:
    """Version 2: index for per-ICCID time-range queries."""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_iccid_time ON signal_history(iccid, unix_time)")


# Ordered list of schema migrations. The position (1-based) is the schema
# version stored in ``PRAGMA user_version``. Append new migrations; never edit
# or reorder existing ones, and never drop data columns automatically.
MIGRATIONS: List[Callable[[sqlite3.Connection], None]] = [
    _migration_1_create_history,
    _migration_2_iccid_index,
]


def latest_schema_version() -> int:
    """The schema version this code writes."""
    return len(MIGRATIONS)


class DBManager:
    """Stores and queries signal history."""

    def __init__(self, db_path: Optional[str] = None):
        """Open the database, creating or migrating it as needed.

        Raises:
            SchemaTooNewError: the file was written by a newer dashboard.
        """
        self.db_path = db_path or default_db_path()
        directory = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(directory, exist_ok=True)
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Bring the database to the latest schema version."""
        with closing(sqlite3.connect(self.db_path, isolation_level=None)) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_history'"
            ).fetchone() is not None

            if version > latest_schema_version():
                raise SchemaTooNewError(
                    f"{self.db_path} has schema version {version}, but this version of the "
                    f"dashboard only understands up to {latest_schema_version()}. "
                    "Update the dashboard or point --db-path at a different file."
                )

            # A database created before versioning existed has the table but no version.
            if version == 0 and has_table:
                version = 1
                conn.execute("PRAGMA user_version = 1")

            if version == latest_schema_version():
                return

            if has_table:  # existing data: keep a copy before changing anything
                self._backup(conn, version)

            for target in range(version + 1, latest_schema_version() + 1):
                self._apply_migration(conn, target)

    def _backup(self, conn: sqlite3.Connection, version: int) -> str:
        """Copy the database to ``<file>.bak-v<version>`` before migrating."""
        backup_path = f"{self.db_path}.bak-v{version}"
        if os.path.exists(backup_path):
            backup_path += time.strftime("-%Y%m%d%H%M%S")
        with closing(sqlite3.connect(backup_path)) as dest:
            conn.backup(dest)
        return backup_path

    @staticmethod
    def _apply_migration(conn: sqlite3.Connection, target: int) -> None:
        """Run migration ``target`` and bump the version in one transaction."""
        conn.execute("BEGIN")
        try:
            MIGRATIONS[target - 1](conn)
            conn.execute(f"PRAGMA user_version = {target}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def log_record(self, state: Dict[str, Any]):
        """Logs current signal and cell metrics into SQLite."""
        sig = state.get("signal", {})
        sc = state.get("serving_cell", {})
        sim = state.get("sim_info", {})
        sys_info = state.get("system_info", {})

        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO signal_history (
                    unix_time, rssi, csq, rsrp, rsrq, sinr, ber, quality_label,
                    operator, mcc, mnc, cell_id, pci, earfcn, band, tac,
                    ip_address, voltage, temperature, iccid, imsi
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now,
                sig.get("rssi", 0),
                sig.get("csq", 0),
                sig.get("rsrp", -140),
                sig.get("rsrq", -20),
                sig.get("sinr", 0),
                sig.get("ber", 0),
                sig.get("quality_label", "Unknown"),
                sc.get("operator", ""),
                sc.get("mcc", ""),
                sc.get("mnc", ""),
                sc.get("cell_id", ""),
                sc.get("pci", 0),
                sc.get("earfcn", 0),
                sc.get("band", ""),
                sc.get("tac", ""),
                sys_info.get("ip_address", ""),
                sys_info.get("voltage", 0),
                sys_info.get("temperature", 0.0),
                sim.get("iccid", ""),
                sim.get("imsi", "")
            ))
            conn.commit()

    def get_history(self, limit: int = 200, start_time: Optional[float] = None, end_time: Optional[float] = None) -> List[Dict[str, Any]]:
        """Fetch historical records from SQLite."""
        query = "SELECT * FROM signal_history"
        params = []
        conditions = []

        if start_time:
            conditions.append("unix_time >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("unix_time <= ?")
            params.append(end_time)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            result = [dict(row) for row in rows]
            result.reverse()  # Return in chronological order
            return result

    def get_stats(self) -> Dict[str, Any]:
        """Get summary stats (min, max, avg RSRP, total records)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_records,
                    MIN(rsrp) as min_rsrp,
                    MAX(rsrp) as max_rsrp,
                    ROUND(AVG(rsrp), 1) as avg_rsrp,
                    ROUND(AVG(rsrq), 1) as avg_rsrq,
                    COUNT(DISTINCT cell_id) as total_cells
                FROM signal_history
            """)
            row = cursor.fetchone()
            if row and row["total_records"] > 0:
                return dict(row)
            return {
                "total_records": 0,
                "min_rsrp": 0,
                "max_rsrp": 0,
                "avg_rsrp": 0,
                "avg_rsrq": 0,
                "total_cells": 0
            }

    def clear_history(self):
        """Clears all logged history."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM signal_history")
            conn.commit()
