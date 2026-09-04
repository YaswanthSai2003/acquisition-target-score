"""
Populate the SQLite database with the synthetic demo dataset.

Usage:
    python seed.py [--db data/ats.db] [--count 60] [--seed 42]
"""
from __future__ import annotations

import argparse

from app.db import clear_leads, connect, init_db, insert_lead
from app.seed_data import generate_leads


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/ats.db")
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    init_db(args.db)
    leads = generate_leads(count=args.count, seed=args.seed)

    with connect(args.db) as conn:
        clear_leads(conn)
        for lead in leads:
            insert_lead(conn, lead)

    print(f"Seeded {len(leads)} leads into {args.db}")


if __name__ == "__main__":
    main()
