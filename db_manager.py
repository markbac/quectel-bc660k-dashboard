import sqlite3
import os
import time
from typing import Dict, Any, List, Optional

DB_FILE = os.path.join(os.path.dirname(__file__), "telemetry.db")

class DBManager:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
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
            # Index for quick time-range queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_unix_time ON signal_history(unix_time)")
            conn.commit()

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
