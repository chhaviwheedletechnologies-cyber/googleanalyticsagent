import json
import os
import math

import requests

METRIC_NAMES = {
    "activeUsers",
    "newUsers",
    "sessions",
    "screenPageViews",
    "engagedSessions",
    "conversions",
    "engagementRate",
    "bounceRate",
}


def _has_analytics_data(value):
    """Detect actual GA4 report rows or usable metric values."""

    if isinstance(value, dict):
        rows = value.get("rows")

        if isinstance(rows, list) and len(rows) > 0:
            return True

        # Detect usable period-comparison values.
        if "current" in value or "previous" in value:
            for key in ("current", "previous"):
                metric_value = value.get(key)
                if (
                    isinstance(metric_value, (int, float))
                    and not isinstance(metric_value, bool)
                    and math.isfinite(metric_value)
                ):
                    return True

        # Detect overview metrics without mistaking row_count,
        # rows_returned, or other metadata for actual analytics.
        for key, item in value.items():
            if key in METRIC_NAMES:
                if (
                    isinstance(item, (int, float))
                    and not isinstance(item, bool)
                    and math.isfinite(item)
                ):
                    return True

        return any(
            _has_analytics_data(item)
            for key, item in value.items()
            if key not in {"row_count", "rows_returned"}
        )

    if isinstance(value, list):
        return any(_has_analytics_data(item) for item in value)

    return False


def _empty_data_insights():
    """Return safe guidance when analytics data is unavailable."""
    return {
        "data_status": "no_data",
        "summary": (
            "No usable analytics data was found in the supplied "
            "reports. Performance trends cannot be assessed yet."
        ),
        "observations": [
            "The supplied reports contain no usable analytics rows "
            "or metric values.",
            "Traffic growth, visitor behaviour, and page performance "
            "cannot be evaluated without data.",
        ],
        "recommendations": [
            "Verify that the GA4 Google tag is installed and deployed "
            "on the live website.",
            "Check GA4 Realtime after visiting the website.",
            "Confirm the GA4 property ID and selected date range.",
            "Retry the reports after GA4 starts collecting data.",
        ],
        "limitations": [
            "No data-backed performance conclusions can be made.",
            "Historical data from before tracking was enabled "
            "may not be available.",
        ],
    }


def _fallback_insights(message):
    """Return a predictable response when AI analysis fails."""
    return {
        "data_status": "analysis_unavailable",
        "summary": (
            "Analytics data may be available, but AI analysis "
            "could not be completed."
        ),
        "observations": [],
        "recommendations": [
            "Check that Ollama is running and the configured model "
            "is available.",
            "Review the error details and retry the insights request.",
        ],
        "limitations": [message],
    }


def _validate_insights(result):
    """Validate the expected structure of the model response."""
    required_keys = {
        "summary",
        "observations",
        "recommendations",
        "limitations",
    }

    if not isinstance(result, dict):
        raise ValueError("AI response must be a JSON object.")

    if not required_keys.issubset(result):
        raise ValueError("AI response is missing required fields.")

    if not isinstance(result["summary"], str):
        raise ValueError("summary must be a string.")

    for key in ("observations", "recommendations", "limitations"):
        if not isinstance(result[key], list):
            raise ValueError(f"{key} must be an array.")

        if not all(isinstance(item, str) for item in result[key]):
            raise ValueError(f"{key} must contain only strings.")

    return {
        "data_status": "analysis_completed",
        "summary": result["summary"],
        "observations": result["observations"],
        "recommendations": result["recommendations"],
        "limitations": result["limitations"],
    }



def _first_report_row(reports, report_name):
    """Return the first row of a report, if available."""
    report = reports.get(report_name, {})
    rows = report.get("rows", [])

    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]

    return {}


def _metric_text(row, metric, label):
    """Format a metric without confusing zero with missing data."""
    if metric not in row or row[metric] is None:
        return None

    return f"{label}: {row[metric]}"



def _build_factual_insights(reports):
    """Build factual insights from GA4 overview, traffic and page metrics."""
    overview = _first_report_row(reports, "overview")
    traffic_rows = reports.get("traffic_sources", {}).get("rows", [])
    page_rows = reports.get("top_pages", {}).get("rows", [])

    observations = []
    recommendations = []
    limitations = []

    metric_labels = [
        ("activeUsers", "Active users"),
        ("newUsers", "New users"),
        ("sessions", "Sessions"),
        ("screenPageViews", "Screen page views"),
        ("engagedSessions", "Engaged sessions"),
        ("conversions", "Reported conversions"),
    ]

    for metric, label in metric_labels:
        text = _metric_text(overview, metric, label)
        if text:
            observations.append(text)

    if not overview:
        limitations.append(
            "No overview metric row was returned; overall metrics "
            "cannot be summarized."
        )

    # Traffic-source observations.
    if isinstance(traffic_rows, list) and traffic_rows:
        for row in traffic_rows[:3]:
            if not isinstance(row, dict):
                continue

            channel = row.get("sessionDefaultChannelGroup", "Unknown")
            sessions = row.get("sessions")

            if sessions is not None:
                observations.append(
                    f"Traffic channel {channel}: {sessions} sessions."
                )
    else:
        limitations.append(
            "No traffic-source rows were returned."
        )

    # Page-level engagement analysis.
    valid_pages = [
        row for row in page_rows
        if isinstance(row, dict)
        and isinstance(row.get("screenPageViews"), (int, float))
        and not isinstance(row.get("screenPageViews"), bool)
        and math.isfinite(row["screenPageViews"])
    ] if isinstance(page_rows, list) else []

    if not valid_pages:
        limitations.append(
            "No usable page-level view metrics were returned."
        )
    else:
        top_page = max(
            valid_pages,
            key=lambda row: row["screenPageViews"],
        )

        observations.append(
            "Highest-viewed page among returned rows: "
            f"{top_page.get('pagePath', 'Unknown')} "
            f"({top_page['screenPageViews']} page views)."
        )

        pages_with_engagement = []
        low_sample_pages = []
        api_like_pages = []

        for row in valid_pages:
            path = str(row.get("pagePath", "Unknown"))
            views = row["screenPageViews"]
            engagement = row.get("engagementRate")
            bounce = row.get("bounceRate")

            if views < 5:
                low_sample_pages.append(path)

            # Flag possible endpoint-like paths for manual verification.
            if (
                path.startswith("/api/")
                or path.endswith(".json")
            ):
                api_like_pages.append(path)

            has_engagement = (
                isinstance(engagement, (int, float))
                and not isinstance(engagement, bool)
                and math.isfinite(engagement)
                and 0 <= engagement <= 1
            )

            has_bounce = (
                isinstance(bounce, (int, float))
                and not isinstance(bounce, bool)
                and math.isfinite(bounce)
                and 0 <= bounce <= 1
            )

            if has_engagement or has_bounce:
                pages_with_engagement.append(row)

            if has_engagement:
                observations.append(
                    f"Page {path}: engagement rate "
                    f"{engagement * 100:.1f}% "
                    f"({views} page views)."
                )

            if has_bounce:
                observations.append(
                    f"Page {path}: bounce rate "
                    f"{bounce * 100:.1f}%."
                )

        # Use explicit, configurable heuristic thresholds.
        # These are investigation flags, not universal GA4 benchmarks.
        high_bounce_pages = [
            row for row in pages_with_engagement
            if isinstance(row.get("bounceRate"), (int, float))
            and not isinstance(row.get("bounceRate"), bool)
            and 0 <= row["bounceRate"] <= 1
            and row["bounceRate"] >= 0.70
            and isinstance(row.get("engagementRate"), (int, float))
            and not isinstance(row.get("engagementRate"), bool)
            and 0 <= row["engagementRate"] <= 1
            and row["engagementRate"] <= 0.25
            and row["screenPageViews"] >= 5
        ]

        if high_bounce_pages:
            for row in high_bounce_pages[:2]:
                path = row.get("pagePath", "Unknown")
                engagement_pct = row["engagementRate"] * 100
                bounce_pct = row["bounceRate"] * 100

                recommendations.append(
                    f"Investigate page {path}: engagement is "
                    f"{engagement_pct:.1f}% and bounce rate is "
                    f"{bounce_pct:.1f}% across "
                    f"{row['screenPageViews']} page views. "
                    "Review the page's content, user journey and "
                    "tracking behaviour before deciding on changes."
                )

        if low_sample_pages:
            limitations.append(
                "Page-level results for paths with fewer than 5 "
                "views are based on a small sample: "
                + ", ".join(low_sample_pages[:5])
                + ". Treat their rates as preliminary."
            )

        if api_like_pages:
            recommendations.append(
                "Verify whether these paths are intended user-facing "
                "pages or API endpoints: "
                + ", ".join(api_like_pages[:5])
                + ". Check the implementation and tracking before "
                "treating them as content pages."
            )

        if not pages_with_engagement:
            limitations.append(
                "Page-level engagement and bounce metrics were not "
                "available in the returned rows."
            )

        if not high_bounce_pages and not api_like_pages:
            recommendations.append(
                "Continue monitoring page-level engagement and bounce "
                "rates as more data accumulates; prioritize pages with "
                "enough views to support meaningful investigation."
            )

    if (
        "engagedSessions" in overview
        and overview["engagedSessions"] == 0
    ):
        recommendations.append(
            "Review engagement reporting and the visitor journey; "
            "zero engaged sessions alone does not identify the cause."
        )

    if (
        "conversions" in overview
        and overview["conversions"] == 0
    ):
        recommendations.append(
            "Review key-event and conversion reporting against business "
            "goals; zero reported conversions alone does not prove "
            "tracking is broken."
        )

    if traffic_rows:
        recommendations.append(
            "Use the returned traffic-channel metrics to assess "
            "acquisition performance."
        )

    if not recommendations:
        recommendations.append(
            "Collect sufficient analytics data before making "
            "performance recommendations."
        )

    return {
        "observations": observations[:12],
        "recommendations": recommendations[:5],
        "limitations": limitations[:5],
    }





def generate_insights(report_data):
    """Generate evidence-based insights from GA4 report data."""

    if not isinstance(report_data, (dict, list)):
        return _fallback_insights(
            "The supplied analytics report has an unsupported format."
        )

    analytics_data = (
        report_data.get("analytics", report_data)
        if isinstance(report_data, dict)
        else report_data
    )

    if not _has_analytics_data(analytics_data):
        return _empty_data_insights()

    if not isinstance(analytics_data, dict):
        return _fallback_insights(
            "Expected named GA4 report sections in the supplied data."
        )

    cleaned_reports = {
        name: value
        for name, value in analytics_data.items()
        if isinstance(value, dict)
        and "error" not in value
        and isinstance(value.get("rows"), list)
    }

    # Only analyze the report sections relevant to historical insights.
    cleaned_reports = {
        name: cleaned_reports[name]
        for name in ("overview", "traffic_sources", "top_pages",
                     "period_comparison")
        if name in cleaned_reports
        and cleaned_reports[name].get("rows")
    }

    if not cleaned_reports:
        return _empty_data_insights()

    factual = _build_factual_insights(cleaned_reports)

    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    ollama_url = os.getenv(
        "OLLAMA_URL",
        "http://localhost:11434/api/generate",
    )

    prompt = f"""
You are a GA4 analyst. Suggest up to 3 additional practical
recommendations based ONLY on the supplied report data.

Return valid JSON with exactly one key:
{{"recommendations": ["recommendation 1"]}}

Rules:
- Do not repeat the supplied recommendations.
- Do not say data is missing if it is present.
- Zero is a reported value, not missing data.
- Never claim zero conversions proves tracking is broken.
- Do not recommend checking bounce rate or time on page unless
  those metrics are relevant and supported by the supplied data.
- Do not invent trends, causes, or comparisons.
- Recommendations must be specific and evidence-based.
- Return an empty array if no additional recommendation is justified.
- Page-level engagement and bounce rates are decimals from 0 to 1;
  interpret them as percentages when describing them.
- Do not infer causes from engagement or bounce rates alone.
- Treat pages with fewer than 5 views as low-sample observations,
  not definitive evidence of poor performance.
- Only discuss page-level engagement when the supplied page rows
  actually contain engagementRate or bounceRate.
- Treat /api/ paths as possible endpoints to verify, not confirmed
  website pages or proof of tracking errors.

Report data:
{json.dumps(cleaned_reports, ensure_ascii=False, allow_nan=False)}

Already generated recommendations:
{json.dumps(factual["recommendations"], ensure_ascii=False)}
"""

    ai_recommendations = []

    try:
        response = requests.post(
            ollama_url,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=(5, 120),
        )
        response.raise_for_status()

        payload = response.json()
        answer = payload.get("response", "")
        result = json.loads(answer)

        extra = result.get("recommendations", [])
        if isinstance(extra, list):
            ai_recommendations = [
                item.strip()
                for item in extra
                if isinstance(item, str) and item.strip()
            ][:3]

    except (
        requests.RequestException,
        ValueError,
        TypeError,
    ):
        # Deterministic factual insights remain available if Ollama fails.
        ai_recommendations = []

    recommendations = factual["recommendations"][:]

    
    
    # Avoid AI recommendations based on very small page samples.
    low_sample_paths = {
        row.get("pagePath")
        for row in cleaned_reports.get("top_pages", {}).get("rows", [])
        if int(row.get("screenPageViews", 0) or 0) < 5
    }

    for recommendation in ai_recommendations:
        if not isinstance(recommendation, str):
            continue

        candidate = recommendation.strip()
        if not candidate:
            continue

        # Skip page-specific recommendations for low-sample pages.
        if any(
            path and path in candidate
            for path in low_sample_paths
        ):
            continue

        # Prevent unsupported benchmarks.
        if "above 50%" in candidate.lower():
            continue

        # Avoid near-duplicate recommendations.
        candidate_words = set(candidate.lower().split())

        is_duplicate = any(
            len(candidate_words & set(existing.lower().split()))
            / max(len(candidate_words), 1) >= 0.65
            for existing in recommendations
        )

        if not is_duplicate:
            recommendations.append(candidate)
