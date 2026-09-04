"""
Acquisition Target Score (ATS) engine.

Business rationale
-------------------
SaaSquatch Leads scores/enriches leads for SALES outreach (who is likely to
buy a product). Caprae's actual end users are searchers/operators looking
for small businesses to ACQUIRE. "Likely to convert" and "likely to be a
good acquisition target" are different, sometimes opposite, signals.

This module scores a business on four factors that matter specifically to
an ETA (Entrepreneurship Through Acquisition) buyer:

1. Succession readiness (30%) - is the owner likely motivated to sell in the
   near term, with no internal successor already lined up?
2. Ownership structure fit (20%) - independent businesses are cleaner deals
   than franchises (franchisor consent, transfer fees) or PE-backed roll-ups
   (usually sold via competitive broker auction, not off-market).
3. Financial fit (30%) - proxy EBITDA relative to the band where first-time
   searchers can realistically finance a deal (roughly $1M-$5M EBITDA).
4. Competitive heat (20%) - businesses in categories that are heavily hyped
   on LinkedIn (HVAC, med spas, home-services roll-ups) draw more competing
   bidders. This directly operationalizes Caprae's own published critique
   that searchers over-index on trendy categories instead of building
   proprietary sourcing advantages (see "Why Most Search Funds Fail").

All four factors, weights, and thresholds are explicit business assumptions,
not ground truth - they are documented here and in the README so a reviewer
can disagree with a specific number without having to trust a black box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OwnershipType(str, Enum):
    INDEPENDENT = "independent"
    FRANCHISE = "franchise"
    PE_BACKED = "pe_backed"
    UNKNOWN = "unknown"


class OwnerAgeBracket(str, Enum):
    UNDER_45 = "under_45"
    FORTY_FIVE_TO_60 = "45_to_60"
    SIXTY_PLUS = "60_plus"
    UNKNOWN = "unknown"


# Industry heat tiers, informed by Caprae's own public commentary on which
# categories are over-competed by searchers ("Why Most Search Funds Fail").
OVERSATURATED_INDUSTRIES = {
    "hvac",
    "medspa",
    "home services",
    "landscaping",
    "pest control",
}
UNDER_RADAR_INDUSTRIES = {
    "commercial laundry",
    "industrial cleaning",
    "specialty manufacturing",
    "medical billing services",
    "equipment rental",
    "environmental testing",
}


@dataclass
class ScoreFactor:
    name: str
    weight: float          # 0-1, fraction of total score
    raw_score: float       # 0-100, this factor's score before weighting
    points: float           # raw_score * weight, contribution to total
    rationale: str


@dataclass
class ScoreResult:
    total_score: float
    tier: str
    factors: list[ScoreFactor] = field(default_factory=list)


@dataclass
class EvidenceAssessment:
    """How complete the decision-critical evidence is for a lead.

    This is deliberately separate from ATS: a company can be an attractive
    target while the underlying evidence is still incomplete. The score is
    evidence coverage, not a probability that an acquisition will succeed.
    """
    confidence_score: int
    label: str
    known_signals: list[str]
    gaps: list[str]
    next_action: str
    caveat: str = "Measures evidence coverage, not probability of deal success."


@dataclass
class LeadFinancials:
    """Minimal shape scoring needs. Kept separate from the ORM model so this
    module has zero DB/framework dependency and is trivially unit-testable."""
    industry: str
    years_in_business: int
    ownership_type: OwnershipType
    owner_age_bracket: OwnerAgeBracket
    has_successor_involved: bool | None  # None = unknown (real data), not "confirmed no successor"
    estimated_annual_revenue: float
    estimated_ebitda_margin: float  # 0-1


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_succession_readiness(lead: LeadFinancials) -> ScoreFactor:
    weight = 0.30
    score = 30.0  # baseline

    if lead.owner_age_bracket == OwnerAgeBracket.SIXTY_PLUS:
        score += 40
    elif lead.owner_age_bracket == OwnerAgeBracket.FORTY_FIVE_TO_60:
        score += 15
    elif lead.owner_age_bracket == OwnerAgeBracket.UNKNOWN:
        score += 5  # no penalty for missing data, but no credit either

    if lead.years_in_business >= 15:
        score += 20
    elif lead.years_in_business >= 8:
        score += 10

    if lead.has_successor_involved:
        score -= 35  # internal succession plan = much less likely to sell

    score = _clamp(score)

    if lead.has_successor_involved:
        rationale = "A successor is already involved, which usually lowers the odds of an outside sale."
    elif lead.has_successor_involved is None:
        rationale = "Succession status is not available from source data; not treated as evidence either way."
    elif lead.owner_age_bracket == OwnerAgeBracket.SIXTY_PLUS:
        rationale = "Owner is likely nearing retirement age with no successor on record - a classic motivated-seller signal."
    elif lead.owner_age_bracket == OwnerAgeBracket.UNKNOWN:
        rationale = "Owner age is unknown; this factor is scored conservatively until enriched."
    else:
        rationale = "No strong succession signal either way based on available data."

    return ScoreFactor("Succession Readiness", weight, score, score * weight, rationale)


def score_ownership_fit(lead: LeadFinancials) -> ScoreFactor:
    weight = 0.20
    mapping = {
        OwnershipType.INDEPENDENT: (90.0, "Independently owned - typically the cleanest deal structure, no franchisor approval needed."),
        OwnershipType.FRANCHISE: (45.0, "Franchise-affiliated - expect franchisor consent, transfer fees, and territory restrictions."),
        OwnershipType.PE_BACKED: (15.0, "Already PE-backed - likely to be sold via a competitive broker auction rather than off-market."),
        OwnershipType.UNKNOWN: (50.0, "Ownership structure not available from source data - scored neutrally rather than guessed."),
    }
    score, rationale = mapping[lead.ownership_type]
    return ScoreFactor("Ownership Structure Fit", weight, score, score * weight, rationale)


def score_financial_fit(lead: LeadFinancials) -> ScoreFactor:
    weight = 0.30
    proxy_ebitda = lead.estimated_annual_revenue * lead.estimated_ebitda_margin

    # Trapezoidal scoring: ramps up into the $1M-$5M sweet spot, flat top,
    # tapers off below $500K (too small to justify deal costs) and above
    # $8M (institutional competition, harder for a first-time searcher to
    # finance without significant outside equity).
    if proxy_ebitda <= 200_000:
        score = 10.0
    elif proxy_ebitda < 1_000_000:
        score = 10 + (proxy_ebitda - 200_000) / (1_000_000 - 200_000) * 70
    elif proxy_ebitda <= 5_000_000:
        score = 95.0
    elif proxy_ebitda < 8_000_000:
        score = 95 - (proxy_ebitda - 5_000_000) / (8_000_000 - 5_000_000) * 55
    else:
        score = 25.0

    score = _clamp(score)

    if 1_000_000 <= proxy_ebitda <= 5_000_000:
        rationale = f"Estimated EBITDA (~${proxy_ebitda:,.0f}) sits in the classic first-time-searcher financing band."
    elif proxy_ebitda < 1_000_000:
        rationale = f"Estimated EBITDA (~${proxy_ebitda:,.0f}) is small - deal costs may not be justified relative to size."
    else:
        rationale = f"Estimated EBITDA (~${proxy_ebitda:,.0f}) is large enough to draw institutional and strategic buyers."

    return ScoreFactor("Financial Fit", weight, score, score * weight, rationale)


def score_competitive_heat(lead: LeadFinancials) -> ScoreFactor:
    weight = 0.20
    industry_key = lead.industry.strip().lower()

    if industry_key in OVERSATURATED_INDUSTRIES:
        score = 25.0
        rationale = f"{lead.industry} is a heavily searched category on LinkedIn - expect more competing buyers per deal."
    elif industry_key in UNDER_RADAR_INDUSTRIES:
        score = 90.0
        rationale = f"{lead.industry} sees far less searcher attention - stronger odds of a proprietary, off-market conversation."
    else:
        score = 60.0
        rationale = f"{lead.industry} has moderate competitive heat based on available signal."

    return ScoreFactor("Competitive Heat", weight, score, score * weight, rationale)


def compute_ats_score(lead: LeadFinancials) -> ScoreResult:
    factors = [
        score_succession_readiness(lead),
        score_ownership_fit(lead),
        score_financial_fit(lead),
        score_competitive_heat(lead),
    ]
    total = sum(f.points for f in factors)
    total = round(_clamp(total), 1)

    if total >= 80:
        tier = "A"
    elif total >= 60:
        tier = "B"
    elif total >= 40:
        tier = "C"
    else:
        tier = "D"

    return ScoreResult(total_score=total, tier=tier, factors=factors)

def assess_diligence_evidence(lead: LeadFinancials, source_note: str = "") -> EvidenceAssessment:
    """Assess coverage of the evidence behind the ATS recommendation.

    Missing values are not treated as negative investment signals. Instead,
    they reduce confidence and become explicit diligence tasks. This avoids
    false precision when public/source data cannot answer questions such as
    owner age, succession intent, or sponsor backing.
    """
    score = 0
    known: list[str] = []
    gaps: list[str] = []

    if lead.industry.strip():
        score += 10
        known.append("Industry signal available")
    else:
        gaps.append("Confirm industry classification")

    if lead.years_in_business > 0:
        score += 10
        known.append("Business-tenure signal available")
    else:
        gaps.append("Confirm years in business")

    if lead.ownership_type != OwnershipType.UNKNOWN:
        score += 20
        known.append("Ownership structure available")
    else:
        gaps.append("Verify ownership structure / sponsor backing")

    if lead.owner_age_bracket != OwnerAgeBracket.UNKNOWN:
        score += 20
        known.append("Owner-age signal available")
    else:
        gaps.append("Verify owner age / retirement timing")

    if lead.has_successor_involved is not None:
        score += 20
        known.append("Succession signal available")
    else:
        gaps.append("Verify succession intent / internal successor")

    if lead.estimated_annual_revenue > 0 and lead.estimated_ebitda_margin > 0:
        score += 20
        known.append("Financial proxy available")
    else:
        gaps.append("Build a revenue / EBITDA proxy")

    note = source_note.lower()
    if "real sba ppp" in note:
        # Revenue/margin are explicitly estimates for this adapter, so do not
        # let a present-but-unverified proxy create false confidence.
        score = max(0, score - 10)
        if "Validate revenue and EBITDA with company financials" not in gaps:
            gaps.append("Validate revenue and EBITDA with company financials")

    if "synthetic demo" in note:
        # Demo rows are useful for evaluating product behavior, not evidence
        # about a real company. Cap the score so the UI never implies otherwise.
        score = min(score, 70)
        gaps.insert(0, "Replace synthetic demo inputs with enriched source data")

    if score >= 80:
        label = "High"
    elif score >= 60:
        label = "Medium"
    else:
        label = "Low"

    if "synthetic demo" in note:
        next_action = "Replace demo inputs with enriched source data before making a real outreach decision."
    elif lead.ownership_type == OwnershipType.UNKNOWN:
        next_action = "Verify ownership / sponsor backing before outreach."
    elif lead.has_successor_involved is None:
        next_action = "Verify succession intent and whether an internal successor is involved."
    elif lead.owner_age_bracket == OwnerAgeBracket.UNKNOWN:
        next_action = "Confirm owner age and likely retirement timing."
    elif "real sba ppp" in note:
        next_action = "Validate revenue and EBITDA with direct company financials before prioritizing outreach."
    else:
        next_action = "Proceed to outreach, then validate financials during first-pass diligence."

    return EvidenceAssessment(
        confidence_score=int(round(_clamp(score))),
        label=label,
        known_signals=known,
        gaps=gaps,
        next_action=next_action,
    )

