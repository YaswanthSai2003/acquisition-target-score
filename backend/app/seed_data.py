"""
Generates a deterministic synthetic dataset for local development,
testing, and demonstration purposes.

Every record is fictional and reproducible from a fixed random seed.
"""
from __future__ import annotations

import random

INDUSTRIES = [
    "HVAC",
    "Landscaping",
    "Pest Control",
    "MedSpa",
    "Home Services",
    "Commercial Laundry",
    "Industrial Cleaning",
    "Specialty Manufacturing",
    "Medical Billing Services",
    "Equipment Rental",
    "Environmental Testing",
    "Auto Repair",
    "Plumbing",
    "Dental Practice",
    "Printing Services",
]

CITIES = [
    ("Columbus", "OH"), ("Tampa", "FL"), ("Boise", "ID"), ("Tulsa", "OK"),
    ("Fresno", "CA"), ("Greenville", "SC"), ("Omaha", "NE"), ("Spokane", "WA"),
    ("Providence", "RI"), ("Richmond", "VA"), ("Madison", "WI"), ("Reno", "NV"),
    ("Chattanooga", "TN"), ("Des Moines", "IA"), ("Albuquerque", "NM"),
]

NAME_PARTS_A = [
    "Summit", "Ironclad", "Meridian", "Cornerstone", "Highland", "Riverbend",
    "Northgate", "Bluepoint", "Silverline", "Ashford", "Redwood", "Foxhollow",
    "Cascade", "Bristol", "Harborview", "Timberline", "Wellspring", "Granite",
]
NAME_SUFFIXES = ["Services", "Group", "Solutions", "Partners", "Co.", "Industries", "LLC"]

OWNERSHIP_TYPES = ["independent", "franchise", "pe_backed"]
AGE_BRACKETS = ["under_45", "45_to_60", "60_plus", "unknown"]


def _make_company_name(rng: random.Random, industry: str) -> str:
    prefix = rng.choice(NAME_PARTS_A)
    suffix = rng.choice(NAME_SUFFIXES)
    return f"{prefix} {industry.split()[0]} {suffix}"


def generate_leads(count: int = 60, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    leads: list[dict] = []

    for _ in range(count):
        industry = rng.choice(INDUSTRIES)
        city, state = rng.choice(CITIES)
        years_in_business = rng.randint(1, 45)

        # Correlate ownership type roughly with realistic base rates rather
        # than pure uniform noise: independents are the most common category.
        ownership_type = rng.choices(OWNERSHIP_TYPES, weights=[0.55, 0.30, 0.15])[0]

        # Older businesses skew toward older owner age brackets.
        if years_in_business >= 20:
            age_bracket = rng.choices(AGE_BRACKETS, weights=[0.05, 0.25, 0.55, 0.15])[0]
        elif years_in_business >= 8:
            age_bracket = rng.choices(AGE_BRACKETS, weights=[0.20, 0.45, 0.20, 0.15])[0]
        else:
            age_bracket = rng.choices(AGE_BRACKETS, weights=[0.55, 0.20, 0.05, 0.20])[0]

        has_successor = rng.random() < (0.30 if years_in_business >= 15 else 0.10)

        employee_count = max(2, int(rng.gauss(18, 12)))
        revenue_per_employee = rng.uniform(120_000, 260_000)
        estimated_annual_revenue = round(employee_count * revenue_per_employee, -3)
        estimated_ebitda_margin = round(rng.uniform(0.08, 0.28), 3)

        leads.append(
            {
                "company_name": _make_company_name(rng, industry),
                "industry": industry,
                "city": city,
                "state": state,
                "employee_count": employee_count,
                "estimated_annual_revenue": estimated_annual_revenue,
                "estimated_ebitda_margin": estimated_ebitda_margin,
                "years_in_business": years_in_business,
                "ownership_type": ownership_type,
                "owner_age_bracket": age_bracket,
                "has_successor_involved": has_successor,
                "website": None,
                "source_note": "Synthetic demo record - not scraped from a live source.",
            }
        )

    return leads
