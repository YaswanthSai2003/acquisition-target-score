"""
Integration tests for the Flask API, using Flask's built-in test client
(no running server / network needed).

Run with:  python -m unittest tests.test_api -v
(from the backend/ directory)
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.db import connect, insert_lead
from app.seed_data import generate_leads


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        db_path = str(Path(self.tmp_dir.name) / "test.db")
        self.app = create_app(db_path=db_path)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        leads = generate_leads(count=25, seed=7)
        with connect(db_path) as conn:
            for lead in leads:
                insert_lead(conn, lead)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_health_check(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "ok"})

    def test_list_leads_returns_items_with_scores(self):
        resp = self.client.get("/api/leads")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["total"], 25)
        self.assertTrue(len(data["items"]) > 0)
        first = data["items"][0]
        self.assertIn("ats_score", first)
        self.assertIn("ats_tier", first)
        self.assertIn(first["ats_tier"], {"A", "B", "C", "D"})

    def test_list_leads_default_sort_is_score_descending(self):
        resp = self.client.get("/api/leads?page_size=200")
        items = resp.get_json()["items"]
        scores = [item["ats_score"] for item in items]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_sort_by_industry_actually_sorts_by_industry(self):
        # Regression test: the frontend table header offers sort_by=industry,
        # but VALID_SORT_FIELDS previously didn't include it, so clicking
        # "Industry" silently fell back to sorting by score instead - a real
        # bug caught by comparing frontend affordances against backend support.
        resp = self.client.get("/api/leads?sort_by=industry&sort_dir=asc&page_size=200")
        items = resp.get_json()["items"]
        industries = [item["industry"] for item in items]
        self.assertEqual(industries, sorted(industries))

    def test_pagination_respects_page_size(self):
        resp = self.client.get("/api/leads?page=1&page_size=5")
        data = resp.get_json()
        self.assertEqual(len(data["items"]), 5)
        self.assertEqual(data["page_size"], 5)

    def test_filter_by_industry(self):
        resp = self.client.get("/api/leads?industry=HVAC&page_size=200")
        data = resp.get_json()
        for item in data["items"]:
            self.assertEqual(item["industry"], "HVAC")

    def test_filter_by_min_score(self):
        resp = self.client.get("/api/leads?min_score=80&page_size=200")
        data = resp.get_json()
        for item in data["items"]:
            self.assertGreaterEqual(item["ats_score"], 80)

    def test_search_matches_company_name_case_insensitively(self):
        all_resp = self.client.get("/api/leads?page_size=200").get_json()
        target_name = all_resp["items"][0]["company_name"]
        needle = target_name.split()[0].lower()

        resp = self.client.get(f"/api/leads?search={needle}&page_size=200")
        data = resp.get_json()
        self.assertTrue(all(needle in item["company_name"].lower() for item in data["items"]))
        self.assertTrue(len(data["items"]) >= 1)

    def test_get_lead_detail_includes_factor_breakdown(self):
        list_resp = self.client.get("/api/leads?page_size=1").get_json()
        lead_id = list_resp["items"][0]["id"]

        resp = self.client.get(f"/api/leads/{lead_id}")
        self.assertEqual(resp.status_code, 200)
        detail = resp.get_json()
        self.assertEqual(detail["id"], lead_id)
        self.assertIn("score", detail)
        self.assertEqual(len(detail["score"]["factors"]), 4)
        for factor in detail["score"]["factors"]:
            self.assertIn("rationale", factor)
        self.assertIn("evidence", detail)
        self.assertIn("confidence_score", detail["evidence"])
        self.assertIn("next_action", detail["evidence"])

    def test_get_lead_detail_404_for_missing_id(self):
        resp = self.client.get("/api/leads/999999")
        self.assertEqual(resp.status_code, 404)

    def test_export_csv_has_expected_header_and_rows(self):
        resp = self.client.get("/api/leads/export.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "text/csv")
        body = resp.get_data(as_text=True)
        lines = body.strip().splitlines()
        self.assertEqual(lines[0], "id,company_name,industry,city,state,employee_count,estimated_annual_revenue,years_in_business,ownership_type,ats_score,ats_tier")
        self.assertEqual(len(lines) - 1, 25)  # header + 25 data rows

    def test_meta_returns_industries_and_tiers(self):
        resp = self.client.get("/api/meta")
        data = resp.get_json()
        self.assertTrue(len(data["industries"]) > 0)
        self.assertEqual(set(data["tiers"]), {"A", "B", "C", "D"})

    def test_stats_summary_tier_counts_sum_to_total(self):
        resp = self.client.get("/api/stats/summary")
        data = resp.get_json()
        self.assertEqual(sum(data["tier_counts"].values()), data["total_leads"])
        self.assertEqual(data["total_leads"], 25)

    def test_stats_summary_respects_active_filters(self):
        # Regression test: stats used to ignore query params entirely and
        # always summarize the full 25-lead dataset even when the table
        # below it was filtered down. Fixed to share the same filter path
        # as /api/leads.
        all_resp = self.client.get("/api/stats/summary").get_json()
        filtered_resp = self.client.get("/api/stats/summary?min_score=80").get_json()
        self.assertLessEqual(filtered_resp["total_leads"], all_resp["total_leads"])

        list_resp = self.client.get("/api/leads?min_score=80&page_size=200").get_json()
        self.assertEqual(filtered_resp["total_leads"], list_resp["total"])


if __name__ == "__main__":
    unittest.main()
