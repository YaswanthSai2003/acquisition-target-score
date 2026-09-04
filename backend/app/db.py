"""
SQLite data-access layer for ATS.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    industry TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    employee_count INTEGER NOT NULL,
    estimated_annual_revenue REAL NOT NULL,
    estimated_ebitda_margin REAL NOT NULL,
    years_in_business INTEGER NOT NULL,
    ownership_type TEXT NOT NULL,
    owner_age_bracket TEXT NOT NULL,
    has_successor_involved INTEGER,  -- nullable: NULL = unknown, not "confirmed no successor"
    website TEXT,
    source_note TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_industry ON leads(industry);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def insert_lead(conn: sqlite3.Connection, lead: dict[str, Any]) -> int:
    cursor = conn.execute(
        """
        INSERT INTO leads (
            company_name, industry, city, state, employee_count,
            estimated_annual_revenue, estimated_ebitda_margin, years_in_business,
            ownership_type, owner_age_bracket, has_successor_involved,
            website, source_note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead["company_name"],
            lead["industry"],
            lead["city"],
            lead["state"],
            lead["employee_count"],
            lead["estimated_annual_revenue"],
            lead["estimated_ebitda_margin"],
            lead["years_in_business"],
            lead["ownership_type"],
            lead["owner_age_bracket"],
            int(lead["has_successor_involved"]) if lead.get("has_successor_involved") is not None else None,
            lead.get("website"),
            lead["source_note"],
        ),
    )
    return cursor.lastrowid


def clear_leads(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM leads")


def fetch_all_leads(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM leads ORDER BY id").fetchall()


def fetch_lead_by_id(conn: sqlite3.Connection, lead_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()


def fetch_distinct_industries(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT industry FROM leads ORDER BY industry").fetchall()
    return [r["industry"] for r in rows]
