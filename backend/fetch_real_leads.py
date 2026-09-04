"""
Pulls REAL small-business records from the SBA's official Paycheck
Protection Program (PPP) FOIA dataset and blends them into the leads
database, instead of relying only on the synthetic generator.

Source (official, public, no API key, no scraping - a direct government
CSV download): https://data.sba.gov/dataset/ppp-foia

What's REAL per matched record:
  - Company name              (BorrowerName)
  - City / state               (BorrowerCity / BorrowerState)
  - Employee count             (JobsReported)
  - Franchise flag             (FranchiseName non-empty -> ownership_type)
  - Industry                   (via NAICS code -> our category, see NAICS_MAP)

What remains an ESTIMATE (this dataset doesn't report it, and no public
dataset legitimately could without asking the owner directly):
  - Annual revenue / EBITDA margin - derived from employee count using the
    same heuristic as seed_data.py, now anchored to a real headcount
  - Owner age bracket, succession involvement - stored as "unknown" / None

Every inserted record's source_note says exactly this - real fields and
estimated fields are never blended together without disclosure.

The source file is ~250-400MB. This script streams it in pandas chunks so
it never holds the full file in memory - a deliberate choice for handling
a real dataset at that scale, not a toy example.

VERIFICATION STATUS: the parsing/mapping path is covered by 16 unit tests
using rows that match the documented PPP schema. The live source is intentionally
not required by the automated test suite because it is a large external file that
can change independently of this repository. Run the preview command below before
using the adapter for a real decision, and review any schema/source changes first.

Usage:
    python fetch_real_leads.py --limit 120          # preview only
    python fetch_real_leads.py --limit 120 --merge  # insert into data/ats.db
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from app.db import connect, init_db, insert_lead

PPP_CSV_URL = (
    "https://data.sba.gov/sites/default/files/distribution/"
    "SBA-OCA-2022-07-001/public_150k_plus_240930.csv"
)

# NAICS code -> our industry taxonomy. PPP's NAICS codes are self-reported
# by the borrower's lender, so expect some noise. Confidence noted inline;
# spot-check a sample against ppp-data-dictionary.xlsx (linked from the
# dataset page) before treating this as authoritative for a real deal.
NAICS_MAP = {
    "238220": "HVAC",                  # Plumbing/Heating/AC Contractors - covers both HVAC and Plumbing in real NAICS; split heuristically below
    "561730": "Landscaping",           # high confidence
    "561710": "Pest Control",          # high confidence
    "811111": "Auto Repair",           # high confidence
    "621210": "Dental Practice",       # high confidence
    "812320": "Commercial Laundry",    # high confidence
    "323111": "Printing Services",     # high confidence
    "561720": "Industrial Cleaning",   # moderate confidence - Janitorial Services is broader than "industrial"
    "541380": "Environmental Testing", # moderate confidence - Testing Laboratories is broader
    "812199": "MedSpa",                # low-moderate confidence - best available proxy (Other Personal Care Services)
    "532412": "Equipment Rental",      # moderate confidence
}

REQUIRED_COLUMNS = [
    "BorrowerName", "BorrowerCity", "BorrowerState", "NAICSCode",
    "JobsReported", "FranchiseName", "BusinessAgeDescription",
]


def _infer_years_in_business(business_age_description: str) -> int:
    """PPP reports a bucketed description, not an exact founding year.
    Mapped to a representative midpoint - explicitly an estimate."""
    if not isinstance(business_age_description, str) or not business_age_description:
        return 8
    desc = business_age_description.lower()
    if "startup" in desc or "2 years or less" in desc or "new business" in desc:
        return 2
    if "existing" in desc or "more than 2" in desc:
        return 12
    return 8


def _infer_ownership_type(franchise_name: str) -> str:
    """PPP data only gives us a reliable signal for franchise status.
    "Corporation" vs "LLC" vs "Sole Proprietorship" tells us nothing
    trustworthy about whether a PE firm holds equity - conflating legal
    entity type with ownership structure was an earlier bug in this
    script. Fixed to report "unknown" rather than manufacture a signal
    the source data doesn't actually contain; ownership scores neutrally
    in that case (see scoring.py OwnershipType.UNKNOWN)."""
    if isinstance(franchise_name, str) and franchise_name.strip().upper() not in ("", "N/A", "NONE", "NAN"):
        return "franchise"
    return "unknown"


def _row_to_lead(row: pd.Series) -> dict | None:
    naics = str(row["NAICSCode"]).strip()
    if naics not in NAICS_MAP:
        return None

    company_name = str(row["BorrowerName"]).strip()
    if not company_name or company_name.lower() == "nan":
        return None

    try:
        employee_count = max(1, int(float(row["JobsReported"])))
    except (ValueError, TypeError):
        return None

    industry = NAICS_MAP[naics]
    if naics == "238220":  # NAICS conflates HVAC and Plumbing; split on name text
        industry = "Plumbing" if "plumb" in company_name.lower() else "HVAC"

    revenue_per_employee = 150_000  # same order-of-magnitude assumption as seed_data.py
    employee_count_val = employee_count
    estimated_annual_revenue = round(employee_count_val * revenue_per_employee, -3)

    city = str(row["BorrowerCity"]).strip() or "Unknown"
    state = str(row["BorrowerState"]).strip() or "NA"

    return {
        "company_name": company_name,
        "industry": industry,
        "city": city,
        "state": state,
        "employee_count": employee_count,
        "estimated_annual_revenue": estimated_annual_revenue,
        "estimated_ebitda_margin": 0.15,  # flat assumption - not present in source data
        "years_in_business": _infer_years_in_business(row.get("BusinessAgeDescription")),
        "ownership_type": _infer_ownership_type(row.get("FranchiseName")),
        "owner_age_bracket": "unknown",   # not present in source data
        "has_successor_involved": None,    # unknown, not "confirmed no successor" - see scoring.py
        "website": None,
        "source_note": (
            "Real SBA PPP FOIA record (data.sba.gov): company name, city/state, employee "
            "count, and franchise flag are real. Revenue, EBITDA margin, owner age, and "
            "succession status are model estimates, not present in the source data."
        ),
    }


def _download_and_filter(limit: int) -> list[dict]:
    print(f"Streaming {PPP_CSV_URL} in chunks (this can take a few minutes)...", file=sys.stderr)
    matched: list[dict] = []

    chunks = pd.read_csv(
        PPP_CSV_URL,
        usecols=lambda c: c in REQUIRED_COLUMNS,
        dtype=str,
        chunksize=50_000,
        low_memory=False,
    )

    for i, chunk in enumerate(chunks):
        missing = [c for c in REQUIRED_COLUMNS if c not in chunk.columns]
        if missing:
            raise RuntimeError(
                f"Expected columns not found in the live CSV: {missing}. "
                "SBA may have renamed a column since this script was written - "
                "check ppp-data-dictionary.xlsx and update REQUIRED_COLUMNS accordingly."
            )

        candidates = chunk[chunk["NAICSCode"].isin(NAICS_MAP.keys())]
        for _, row in candidates.iterrows():
            lead = _row_to_lead(row)
            if lead:
                matched.append(lead)
            if len(matched) >= limit:
                return matched

        print(f"  scanned chunk {i + 1} (~{(i + 1) * 50_000:,} rows), matched so far: {len(matched)}", file=sys.stderr)

    return matched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=120, help="Max real records to pull")
    parser.add_argument("--db", default="data/ats.db")
    parser.add_argument("--merge", action="store_true", help="Insert into the DB (default is preview-only)")
    args = parser.parse_args()

    leads = _download_and_filter(args.limit)
    print(f"\nMatched {len(leads)} real records.")

    by_industry: dict[str, int] = {}
    for lead in leads:
        by_industry[lead["industry"]] = by_industry.get(lead["industry"], 0) + 1
    for industry, count in sorted(by_industry.items(), key=lambda x: -x[1]):
        print(f"  {industry:<25} {count}")

    if args.merge:
        init_db(args.db)
        with connect(args.db) as conn:
            for lead in leads:
                insert_lead(conn, lead)
        print(f"\nInserted {len(leads)} real leads into {args.db} (existing rows kept).")
    else:
        print("\nPreview only - re-run with --merge to insert these into the database.")


if __name__ == "__main__":
    main()
