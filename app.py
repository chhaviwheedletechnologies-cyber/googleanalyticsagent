import re
from datetime import datetime, timezone, date

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

from services.ga4_service import GA4Service
from services.storage import save_report
from services.ai_insights import generate_insights

load_dotenv()

app = FastAPI(
    title="Google Analytics Agent",
    description=(
        "Fetch GA4 analytics, analyze traffic, "
        "generate AI insights, and save reports."
    ),
    version="1.0.0",
)


@app.get("/")
def home():
    return {
        "agent": "Google Analytics Agent",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


def fetch_service():
    try:
        return GA4Service()
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


def validate_date_range(start_date: str, end_date: str):
    """Validate GA4 absolute and relative date inputs."""

    def parse_date(value):
        if value in ("today", "yesterday"):
            return None

        if re.fullmatch(r"\d+daysAgo", value):
            return None

        try:
            return date.fromisoformat(value)
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid date '{value}'. Use YYYY-MM-DD, "
                "today, yesterday, or NdaysAgo (e.g. 7daysAgo)."
            )

    start = parse_date(start_date)
    end = parse_date(end_date)

    if start is not None and end is not None and start > end:
        raise ValueError(
            "start_date must be earlier than or equal to end_date."
        )


def check_dates(start_date: str, end_date: str):
    try:
        validate_date_range(start_date, end_date)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


def analyze_data_quality(data, report_name=None):
    """Summarize data availability for GA4 reports."""

    reports = {}

    known_reports = (
        "overview",
        "traffic_sources",
        "top_pages",
        "traffic_by_date",
        "traffic_by_hour",
        "detailed_traffic_sources",
        "landing_pages",
        "device_technology",
    )

    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        name = report_name or "report"
        row_count = len(data["rows"])

        reports[name] = {
            "status": "data_available" if row_count > 0 else "no_data",
            "rows_returned": row_count,
        }

    elif isinstance(data, dict):
        
        for name in known_reports:
            payload = data.get(name)

            if isinstance(payload, dict) and isinstance(
                payload.get("rows"), list
            ):
                row_count = len(payload["rows"])
                reports[name] = {
                    "status": (
                        "data_available" if row_count > 0 else "no_data"
                    ),
                    "rows_returned": row_count,
                }

    total_rows = sum(item["rows_returned"] for item in reports.values())
    has_data = total_rows > 0

    return {
        "status": "data_available" if has_data else "no_data",
        "total_rows_returned": total_rows,
        "reports": reports,
        "recommendations": (
            []
            if has_data
            else [
                "Verify that the GA4 Google tag is deployed.",
                "Check GA4 Realtime for incoming events.",
                "Confirm the property ID and selected date range.",
            ]
        ),
    }


def build_report(
    report_type,
    service,
    start_date,
    end_date,
    data,
    save_to_db,
):
    report = {
        "report_type": report_type,
        "property_id": service.property_id,
        "date_range": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "data_quality": analyze_data_quality(
            data, report_name=report_type
        ),
    }

    if save_to_db:
        report["storage"] = save_report(report)

    return report


@app.get("/analytics/overview")
def analytics_overview(
    start_date: str = Query("7daysAgo"),
    end_date: str = Query("yesterday"),
    save_to_db: bool = True,
):
    check_dates(start_date, end_date)
    service = fetch_service()

    try:
        data = service.get_overview(start_date, end_date)
        return build_report(
            "overview",
            service,
            start_date,
            end_date,
            data,
            save_to_db,
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"GA4 overview failed: {error}",
        )


@app.get("/analytics/stream")
def get_stream_data():
    try:
        service = GA4Service()
        return service.get_stream_data()
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))

@app.get("/analytics/stream/realtime")
def get_realtime_stream_data():
    service = fetch_service()

    try:
        return service.get_realtime_stream_data()
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"GA4 realtime stream report failed: {error}",
        )
        

@app.get("/analytics/stream/complete")
def complete_stream_analytics(
    start_date: str = Query("7daysAgo"),
    end_date: str = Query("yesterday"),
    limit: int = Query(10, ge=1, le=100),
    include_insights: bool = Query(True),
    save_to_db: bool = False,
):
    """
    Unified GA4 stream analytics:
    stream configuration, historical reports,
    realtime events, data quality, and AI insights.
    """
    service = fetch_service()

    # Validate the requested date range using the existing helper.
    try:
        check_dates(start_date, end_date)
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date range: {error}",
        )

    # Collect reports independently so one failure
    # does not prevent other reports from being returned.
    reports = {}

    report_tasks = {
        "overview": lambda: service.get_overview(
            start_date, end_date
        ),
        "traffic_sources": lambda: service.get_traffic_sources(
            start_date, end_date, limit
        ),
        "top_pages": lambda: service.get_top_pages(
            start_date, end_date, limit
        ),
        "traffic_by_date": lambda: service.get_traffic_by_date(
            start_date, end_date
        ),
        "traffic_by_hour": lambda: service.get_traffic_by_hour(
            start_date, end_date
        ),
        "detailed_traffic_sources": lambda:
            service.get_detailed_traffic_sources(
                start_date, end_date, limit
            ),
        "landing_pages": lambda: service.get_landing_pages(
            start_date, end_date, limit
        ),
        "device_technology": lambda:
            service.get_device_technology(
                start_date, end_date, limit
            ),
        "period_comparison": lambda:
            service.get_period_comparison(
                start_date, end_date
            ),
    }

    for report_name, report_function in report_tasks.items():
        try:
            reports[report_name] = report_function()
        except Exception as error:
            reports[report_name] = {
                "error": str(error)
            }

    # Fetch stream configuration.
    try:
        stream_data = service.get_stream_data()
    except Exception as error:
        stream_data = {"error": str(error)}

    # Fetch realtime activity.
    try:
        realtime_data = service.get_realtime_stream_data()
    except Exception as error:
        realtime_data = {"error": str(error)}

    response = {
        "report_type": "complete_stream_analytics",
        "property_id": service.property_id,
        "date_range": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "stream": stream_data,
        "realtime": realtime_data,
        "analytics": reports,
    }

    # Evaluate data quality using the existing helper.
    try:
        response["data_quality"] = analyze_data_quality(
            reports
        )
    except Exception as error:
        response["data_quality"] = {
            "error": str(error)
        }

    # Generate AI insights only when requested.
    if include_insights:
        try:
            response["insights"] = generate_insights(
                reports
            )
        except Exception as error:
            response["insights"] = {
                "error": str(error)
            }

    # Save the unified response only when explicitly requested.
    if save_to_db:
        try:
            response["storage"] = save_report(response)
        except Exception as error:
            response["storage"] = {
                "error": str(error)
            }

    return response



@app.get("/analytics/traffic-sources")
def traffic_sources(
    start_date: str = Query("7daysAgo"),
    end_date: str = Query("yesterday"),
    limit: int = Query(20, ge=1, le=100),
    save_to_db: bool = True,
):
    check_dates(start_date, end_date)
    service = fetch_service()

    try:
        data = service.get_traffic_sources(start_date, end_date, limit)
        return build_report(
            "traffic_sources",
            service,
            start_date,
            end_date,
            data,
            save_to_db,
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"GA4 traffic report failed: {error}",
        )


@app.get("/analytics/top-pages")
def top_pages(
    start_date: str = Query("7daysAgo"),
    end_date: str = Query("yesterday"),
    limit: int = Query(20, ge=1, le=100),
    save_to_db: bool = True,
):
    check_dates(start_date, end_date)
    service = fetch_service()

    try:
        data = service.get_top_pages(start_date, end_date, limit)
        return build_report(
            "top_pages",
            service,
            start_date,
            end_date,
            data,
            save_to_db,
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"GA4 page report failed: {error}",
        )


@app.get("/analytics/insights")
def analytics_insights(
    start_date: str = Query("7daysAgo"),
    end_date: str = Query("yesterday"),
    save_to_db: bool = True,
):
    check_dates(start_date, end_date)
    service = fetch_service()

    try:
        data = {
            "overview": service.get_overview(start_date, end_date),
            "traffic_sources": service.get_traffic_sources(
                start_date, end_date, 10
            ),
            "top_pages": service.get_top_pages(start_date, end_date, 10),
        }

        report = {
            "report_type": "ai_insights",
            "property_id": service.property_id,
            "date_range": {
                "start_date": start_date,
                "end_date": end_date,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_data": data,
            "data_quality": analyze_data_quality(data),
            "insights": generate_insights(data),
        }

        if save_to_db:
            report["storage"] = save_report(report)

        return report

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Analytics insights failed: {error}",
        )


def add_new_report_endpoint(
    report_type,
    method_name,
    start_date,
    end_date,
    limit=100,
    save_to_db=False,
):
    check_dates(start_date, end_date)
    service = fetch_service()

    try:
        method = getattr(service, method_name)

        if method_name in (
            "get_detailed_traffic_sources",
            "get_landing_pages",
            "get_device_technology",
        ):
            data = method(start_date, end_date, limit)
        else:
            data = method(start_date, end_date)

        return build_report(
            report_type,
            service,
            start_date,
            end_date,
            data,
            save_to_db,
        )

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"{report_type} report failed: {error}",
        )


@app.get("/analytics/traffic-by-date")
def traffic_by_date(
    start_date: str = Query("7daysAgo"),
    end_date: str = Query("yesterday"),
    save_to_db: bool = False,
):
    return add_new_report_endpoint(
        "traffic_by_date",
        "get_traffic_by_date",
        start_date,
        end_date,
        save_to_db=save_to_db,
    )


@app.get("/analytics/traffic-by-hour")
def traffic_by_hour(
    start_date: str = Query("7daysAgo"),
    end_date: str = Query("yesterday"),
    save_to_db: bool = False,
):
    return add_new_report_endpoint(
        "traffic_by_hour",
        "get_traffic_by_hour",
        start_date,
        end_date,
        save_to_db=save_to_db,
    )


@app.get("/analytics/detailed-traffic-sources")
def detailed_traffic_sources(
    start_date: str = Query("7daysAgo"),
    end_date: str = Query("yesterday"),
    limit: int = Query(100, ge=1, le=1000),
    save_to_db: bool = False,
):
    return add_new_report_endpoint(
        "detailed_traffic_sources",
        "get_detailed_traffic_sources",
        start_date,
        end_date,
        limit,
        save_to_db,
    )


@app.get("/analytics/landing-pages")
def landing_pages(
    start_date: str = Query("7daysAgo"),
    end_date: str = Query("yesterday"),
    limit: int = Query(100, ge=1, le=1000),
    save_to_db: bool = False,
):
    return add_new_report_endpoint(
        "landing_pages",
        "get_landing_pages",
        start_date,
        end_date,
        limit,
        save_to_db,
    )


@app.get("/analytics/device-technology")
def device_technology(
    start_date: str = Query("7daysAgo"),
    end_date: str = Query("yesterday"),
    limit: int = Query(100, ge=1, le=1000),
    save_to_db: bool = False,
):
    return add_new_report_endpoint(
        "device_technology",
        "get_device_technology",
        start_date,
        end_date,
        limit,
        save_to_db,
    )


@app.get("/analytics/period-comparison")
def period_comparison(
    start_date: str = Query("2026-10-01"),
    end_date: str = Query("2026-10-07"),
    save_to_db: bool = False,
):
    check_dates(start_date, end_date)
    service = fetch_service()

    try:
        data = service.get_period_comparison(start_date, end_date)

        report = {
            "report_type": "period_comparison",
            "property_id": service.property_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **data,
        }

        if save_to_db:
            report["storage"] = save_report(report)

        return report

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Period comparison failed: {error}",
        )