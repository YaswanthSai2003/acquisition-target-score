"""
Tests for fetch_real_leads.py's parsing/mapping logic. These do NOT hit
the network - they construct rows matching the live PPP CSV's documented
schema and verify the mapping logic. The download itself (pandas.read_csv
against the live URL) is not covered here since it requires network
access this test suite deliberately avoids depending on.

Run with:  python -m unittest tests.test_fetch_real_leads -v
"""
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fetch_real_leads import _infer_ownership_type, _infer_years_in_business, _row_to_lead


def make_row(**overrides) -> pd.Series:
    defaults = dict(
        BorrowerName="Test Co LLC",
        BorrowerCity="Tulsa",
        BorrowerState="OK",
        NAICSCode="561730",
        JobsReported="10",
        FranchiseName="",
        BusinessType="Limited Liability Company(LLC)",
        BusinessAgeDescription="Existing or more than 2 years old",
    )
    defaults.update(overrides)
    return pd.Series(defaults)


class TestYearsInBusinessInference(unittest.TestCase):
    def test_startup_description_maps_to_short_tenure(self):
        self.assertEqual(_infer_years_in_business("Startup, loan funds will be used to start a new business"), 2)

    def test_existing_description_maps_to_longer_tenure(self):
        self.assertEqual(_infer_years_in_business("Existing or more than 2 years old"), 12)

    def test_missing_description_defaults_safely(self):
        self.assertEqual(_infer_years_in_business(""), 8)
        self.assertEqual(_infer_years_in_business(None), 8)
        self.assertEqual(_infer_years_in_business(float("nan")), 8)


class TestOwnershipInference(unittest.TestCase):
    def test_franchise_name_present_wins(self):
        self.assertEqual(_infer_ownership_type("Some Franchise Group"), "franchise")

    def test_placeholder_franchise_values_are_ignored(self):
        for placeholder in ["", "N/A", "NONE", "n/a"]:
            self.assertEqual(_infer_ownership_type(placeholder), "unknown")

    def test_no_franchise_signal_is_unknown_not_guessed(self):
        # Regression test: this used to infer "pe_backed" from BusinessType
        # containing "Corporation", which is not a trustworthy signal -
        # incorporation says nothing about who holds equity. Fixed to
        # report "unknown" rather than manufacture a signal PPP data
        # doesn't actually contain.
        self.assertEqual(_infer_ownership_type(""), "unknown")
        self.assertEqual(_infer_ownership_type(None), "unknown")


class TestRowToLead(unittest.TestCase):
    def test_naics_238220_splits_to_plumbing_by_name(self):
        row = make_row(NAICSCode="238220", BorrowerName="Main Street Plumbing LLC")
        lead = _row_to_lead(row)
        self.assertEqual(lead["industry"], "Plumbing")

    def test_naics_238220_defaults_to_hvac_without_plumbing_in_name(self):
        row = make_row(NAICSCode="238220", BorrowerName="Ace Comfort Heating & Air")
        lead = _row_to_lead(row)
        self.assertEqual(lead["industry"], "HVAC")

    def test_unmapped_naics_returns_none(self):
        row = make_row(NAICSCode="722511")  # restaurants - not in our taxonomy
        self.assertIsNone(_row_to_lead(row))

    def test_missing_company_name_returns_none(self):
        row = make_row(BorrowerName="")
        self.assertIsNone(_row_to_lead(row))

    def test_non_numeric_jobs_reported_returns_none_not_crash(self):
        row = make_row(JobsReported="not_a_number")
        self.assertIsNone(_row_to_lead(row))

    def test_valid_row_produces_disclosed_source_note(self):
        lead = _row_to_lead(make_row())
        self.assertIn("Real SBA PPP FOIA record", lead["source_note"])
        self.assertIn("model estimates", lead["source_note"])

    def test_owner_age_marked_unknown_and_successor_status_is_none_not_false(self):
        lead = _row_to_lead(make_row())
        self.assertEqual(lead["owner_age_bracket"], "unknown")
        # Must be None (unknown), not False (which would falsely claim we
        # confirmed no successor exists) - see scoring.py's tri-state handling.
        self.assertIsNone(lead["has_successor_involved"])

    def test_ownership_type_is_unknown_without_franchise_signal(self):
        lead = _row_to_lead(make_row(FranchiseName="", BusinessType="Corporation"))
        self.assertEqual(lead["ownership_type"], "unknown")

    def test_ownership_type_is_franchise_when_signal_present(self):
        lead = _row_to_lead(make_row(FranchiseName="Some Franchise Group"))
        self.assertEqual(lead["ownership_type"], "franchise")

    def test_revenue_estimate_scales_with_real_employee_count(self):
        small = _row_to_lead(make_row(JobsReported="5"))
        large = _row_to_lead(make_row(JobsReported="50"))
        self.assertLess(small["estimated_annual_revenue"], large["estimated_annual_revenue"])


if __name__ == "__main__":
    unittest.main()
