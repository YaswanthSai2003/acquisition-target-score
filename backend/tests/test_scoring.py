"""
Unit tests for the ATS scoring engine.

Run with:  python -m unittest tests.test_scoring -v
(from the backend/ directory)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scoring import (
    LeadFinancials,
    OwnerAgeBracket,
    OwnershipType,
    assess_diligence_evidence,
    compute_ats_score,
    score_competitive_heat,
    score_financial_fit,
    score_ownership_fit,
    score_succession_readiness,
)


def make_lead(**overrides) -> LeadFinancials:
    defaults = dict(
        industry="specialty manufacturing",
        years_in_business=20,
        ownership_type=OwnershipType.INDEPENDENT,
        owner_age_bracket=OwnerAgeBracket.SIXTY_PLUS,
        has_successor_involved=False,
        estimated_annual_revenue=8_000_000,
        estimated_ebitda_margin=0.25,  # -> $2M proxy EBITDA
    )
    defaults.update(overrides)
    return LeadFinancials(**defaults)


class TestSuccessionReadiness(unittest.TestCase):
    def test_older_owner_no_successor_scores_high(self):
        lead = make_lead(owner_age_bracket=OwnerAgeBracket.SIXTY_PLUS, has_successor_involved=False)
        factor = score_succession_readiness(lead)
        self.assertGreaterEqual(factor.raw_score, 80)

    def test_successor_involved_lowers_score_regardless_of_age(self):
        with_successor = score_succession_readiness(make_lead(has_successor_involved=True))
        without_successor = score_succession_readiness(make_lead(has_successor_involved=False))
        self.assertLess(with_successor.raw_score, without_successor.raw_score)

    def test_unknown_age_is_not_penalized_below_baseline(self):
        factor = score_succession_readiness(
            make_lead(owner_age_bracket=OwnerAgeBracket.UNKNOWN, years_in_business=1, has_successor_involved=False)
        )
        self.assertGreaterEqual(factor.raw_score, 0)

    def test_none_successor_status_scores_same_as_false_but_rationale_differs(self):
        # Regression test: has_successor_involved=None (genuinely unknown,
        # from real SBA data) must not be scored as if it were confirmed
        # False (no successor). The math already treats them the same
        # (neither triggers the penalty) - this locks that in and checks
        # the rationale text is honest about which case it is.
        none_factor = score_succession_readiness(make_lead(has_successor_involved=None))
        false_factor = score_succession_readiness(make_lead(has_successor_involved=False))
        self.assertEqual(none_factor.raw_score, false_factor.raw_score)
        self.assertIn("not available", none_factor.rationale)
        self.assertNotIn("not available", false_factor.rationale)

    def test_score_never_exceeds_bounds(self):
        factor = score_succession_readiness(
            make_lead(owner_age_bracket=OwnerAgeBracket.SIXTY_PLUS, years_in_business=50, has_successor_involved=False)
        )
        self.assertTrue(0 <= factor.raw_score <= 100)


class TestOwnershipFit(unittest.TestCase):
    def test_independent_scores_highest_pe_backed_lowest(self):
        independent = score_ownership_fit(make_lead(ownership_type=OwnershipType.INDEPENDENT)).raw_score
        franchise = score_ownership_fit(make_lead(ownership_type=OwnershipType.FRANCHISE)).raw_score
        pe_backed = score_ownership_fit(make_lead(ownership_type=OwnershipType.PE_BACKED)).raw_score
        self.assertGreater(independent, franchise)
        self.assertGreater(franchise, pe_backed)

    def test_unknown_ownership_scores_neutrally_between_extremes(self):
        unknown = score_ownership_fit(make_lead(ownership_type=OwnershipType.UNKNOWN)).raw_score
        independent = score_ownership_fit(make_lead(ownership_type=OwnershipType.INDEPENDENT)).raw_score
        pe_backed = score_ownership_fit(make_lead(ownership_type=OwnershipType.PE_BACKED)).raw_score
        self.assertLess(pe_backed, unknown)
        self.assertLess(unknown, independent)


class TestFinancialFit(unittest.TestCase):
    def test_sweet_spot_ebitda_scores_near_max(self):
        lead = make_lead(estimated_annual_revenue=10_000_000, estimated_ebitda_margin=0.3)  # $3M EBITDA
        factor = score_financial_fit(lead)
        self.assertGreaterEqual(factor.raw_score, 90)

    def test_tiny_business_scores_low(self):
        lead = make_lead(estimated_annual_revenue=200_000, estimated_ebitda_margin=0.1)  # $20k EBITDA
        factor = score_financial_fit(lead)
        self.assertLessEqual(factor.raw_score, 15)

    def test_very_large_business_tapers_but_does_not_hit_zero(self):
        lead = make_lead(estimated_annual_revenue=100_000_000, estimated_ebitda_margin=0.2)  # $20M EBITDA
        factor = score_financial_fit(lead)
        self.assertTrue(0 < factor.raw_score < 40)

    def test_zero_revenue_does_not_crash(self):
        lead = make_lead(estimated_annual_revenue=0, estimated_ebitda_margin=0.2)
        factor = score_financial_fit(lead)
        self.assertEqual(factor.raw_score, 10.0)


class TestCompetitiveHeat(unittest.TestCase):
    def test_oversaturated_industry_penalized(self):
        factor = score_competitive_heat(make_lead(industry="HVAC"))
        self.assertLessEqual(factor.raw_score, 30)

    def test_under_radar_industry_rewarded(self):
        factor = score_competitive_heat(make_lead(industry="Specialty Manufacturing"))
        self.assertGreaterEqual(factor.raw_score, 80)

    def test_unlisted_industry_gets_neutral_score(self):
        factor = score_competitive_heat(make_lead(industry="Artisanal Cheese Distribution"))
        self.assertEqual(factor.raw_score, 60.0)

    def test_industry_matching_is_case_insensitive(self):
        lower = score_competitive_heat(make_lead(industry="hvac")).raw_score
        upper = score_competitive_heat(make_lead(industry="HVAC")).raw_score
        self.assertEqual(lower, upper)


class TestDiligenceEvidence(unittest.TestCase):
    def test_complete_non_demo_record_has_high_evidence_coverage(self):
        assessment = assess_diligence_evidence(make_lead(), "Verified enrichment record")
        self.assertEqual(assessment.confidence_score, 100)
        self.assertEqual(assessment.label, "High")
        self.assertEqual(assessment.gaps, [])

    def test_unknown_owner_signals_reduce_confidence_without_lowering_ats_by_themselves(self):
        lead = make_lead(
            ownership_type=OwnershipType.UNKNOWN,
            owner_age_bracket=OwnerAgeBracket.UNKNOWN,
            has_successor_involved=None,
        )
        assessment = assess_diligence_evidence(lead, "Real SBA PPP FOIA record")
        self.assertLess(assessment.confidence_score, 60)
        self.assertIn("Verify ownership structure / sponsor backing", assessment.gaps)
        self.assertIn("Verify succession intent / internal successor", assessment.gaps)

    def test_synthetic_demo_is_never_presented_as_high_confidence_real_evidence(self):
        assessment = assess_diligence_evidence(
            make_lead(),
            "Synthetic demo record - not scraped from a live source.",
        )
        self.assertEqual(assessment.confidence_score, 70)
        self.assertEqual(assessment.label, "Medium")
        self.assertIn("Replace synthetic demo inputs", assessment.gaps[0])


class TestComputeAtsScore(unittest.TestCase):
    def test_ideal_lead_lands_in_tier_a(self):
        lead = make_lead(
            industry="specialty manufacturing",
            years_in_business=20,
            ownership_type=OwnershipType.INDEPENDENT,
            owner_age_bracket=OwnerAgeBracket.SIXTY_PLUS,
            has_successor_involved=False,
            estimated_annual_revenue=10_000_000,
            estimated_ebitda_margin=0.3,
        )
        result = compute_ats_score(lead)
        self.assertEqual(result.tier, "A")
        self.assertGreaterEqual(result.total_score, 80)

    def test_weak_lead_lands_in_tier_d(self):
        lead = make_lead(
            industry="HVAC",
            years_in_business=2,
            ownership_type=OwnershipType.PE_BACKED,
            owner_age_bracket=OwnerAgeBracket.UNDER_45,
            has_successor_involved=True,
            estimated_annual_revenue=150_000,
            estimated_ebitda_margin=0.05,
        )
        result = compute_ats_score(lead)
        self.assertEqual(result.tier, "D")

    def test_total_score_matches_sum_of_factor_points(self):
        lead = make_lead()
        result = compute_ats_score(lead)
        self.assertAlmostEqual(result.total_score, sum(f.points for f in result.factors), delta=0.15)

    def test_returns_exactly_four_factors(self):
        result = compute_ats_score(make_lead())
        self.assertEqual(len(result.factors), 4)

    def test_score_is_always_in_valid_range(self):
        lead = make_lead()
        result = compute_ats_score(lead)
        self.assertTrue(0 <= result.total_score <= 100)


if __name__ == "__main__":
    unittest.main()
