from __future__ import annotations

import csv
import io

from flask import Blueprint, Response, current_app, jsonify, request

from app.db import connect, fetch_all_leads, fetch_distinct_industries, fetch_lead_by_id
from app.serializers import lead_row_to_detail_dict, lead_row_to_summary_dict

api = Blueprint("api", __name__, url_prefix="/api")

VALID_SORT_FIELDS = {
    "ats_score": "ats_score",
    "company_name": "company_name",
    "industry": "industry",
    "estimated_annual_revenue": "estimated_annual_revenue",
    "years_in_business": "years_in_business",
}


def _db_path() -> str:
    return current_app.config["DB_PATH"]


def _load_filtered_summaries() -> list[dict]:
    """Load, score, filter, and sort lead summaries."""
    with connect(_db_path()) as conn:
        rows = fetch_all_leads(conn)
        summaries = [lead_row_to_summary_dict(r) for r in rows]

    industry = request.args.get("industry")
    if industry:
        wanted = {i.strip().lower() for i in industry.split(",") if i.strip()}
        summaries = [s for s in summaries if s["industry"].lower() in wanted]

    tier = request.args.get("tier")
    if tier:
        wanted_tiers = {t.strip().upper() for t in tier.split(",") if t.strip()}
        summaries = [s for s in summaries if s["ats_tier"] in wanted_tiers]

    min_score = request.args.get("min_score", type=float)
    if min_score is not None:
        summaries = [s for s in summaries if s["ats_score"] >= min_score]

    search = request.args.get("search")
    if search:
        needle = search.strip().lower()
        summaries = [s for s in summaries if needle in s["company_name"].lower()]

    sort_by = request.args.get("sort_by", default="ats_score")
    sort_field = VALID_SORT_FIELDS.get(sort_by, "ats_score")
    sort_dir = request.args.get("sort_dir", default="desc")
    reverse = sort_dir != "asc"
    summaries.sort(key=lambda s: s[sort_field], reverse=reverse)

    return summaries


@api.get("/health")
def health():
    return jsonify({"status": "ok"})


@api.get("/leads")
def list_leads():
    summaries = _load_filtered_summaries()

    page = request.args.get("page", default=1, type=int)
    page_size = request.args.get("page_size", default=25, type=int)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))

    total = len(summaries)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = summaries[start:end]

    return jsonify(
        {
            "items": page_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }
    )


@api.get("/leads/<int:lead_id>")
def get_lead(lead_id: int):
    with connect(_db_path()) as conn:
        row = fetch_lead_by_id(conn, lead_id)
    if row is None:
        return jsonify({"error": "not_found", "message": f"No lead with id {lead_id}"}), 404
    return jsonify(lead_row_to_detail_dict(row))


@api.get("/leads/export.csv")
def export_leads_csv():
    summaries = _load_filtered_summaries()

    buffer = io.StringIO()
    fieldnames = [
        "id", "company_name", "industry", "city", "state", "employee_count",
        "estimated_annual_revenue", "years_in_business", "ownership_type",
        "ats_score", "ats_tier",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(summaries)

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=acquisition_targets.csv"},
    )


@api.get("/meta")
def meta():
    with connect(_db_path()) as conn:
        industries = fetch_distinct_industries(conn)
    return jsonify({"industries": industries, "tiers": ["A", "B", "C", "D"]})


@api.get("/stats/summary")
def stats_summary():
    """Reflects the SAME filters as /api/leads, not the whole dataset.

    Regression note: this used to always summarize all 60 leads regardless
    of active filters, so the top stats bar looked inconsistent with a
    filtered table underneath it. Fixed by reusing the same filter pipeline.
    """
    summaries = _load_filtered_summaries()

    tier_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for s in summaries:
        tier_counts[s["ats_tier"]] += 1

    return jsonify(
        {
            "total_leads": len(summaries),
            "tier_counts": tier_counts,
            "average_score": round(sum(s["ats_score"] for s in summaries) / len(summaries), 1) if summaries else 0,
        }
    )
