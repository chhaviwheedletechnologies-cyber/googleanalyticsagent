import os
from google.analytics.admin_v1beta import AnalyticsAdminServiceClient
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
    RunRealtimeReportRequest,
)
from google.oauth2 import service_account


class GA4Service:
    def __init__(self):
        self.property_id = os.getenv("GA4_PROPERTY_ID", "").strip()
        credentials_path = os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS", ""
        ).strip()

        if not self.property_id:
            raise ValueError(
                "GA4_PROPERTY_ID missing in .env"
            )

        if not credentials_path or not os.path.isfile(credentials_path):
            raise ValueError(
                "Google service-account JSON file not found. "
                "Check GOOGLE_APPLICATION_CREDENTIALS in .env"
            )

        credentials = (
            service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=[
                    "https://www.googleapis.com/auth/analytics.readonly"
                ],
            )
        )
        
        self.credentials = credentials

        self.client = BetaAnalyticsDataClient(
            credentials=credentials
        )
        
    def get_stream_data(self):
        admin_client = AnalyticsAdminServiceClient(
            credentials=self.credentials
        )

        streams = admin_client.list_data_streams(
            parent=f"properties/{self.property_id}"
        )

        result = []

        for stream in streams:
            item = {
                "stream_name": stream.display_name,
                "stream_id": stream.name.split("/")[-1],
                "stream_type": str(stream.type_),
            }

            if stream.web_stream_data:
                item["website_url"] = (
                    stream.web_stream_data.default_uri
                )
                item["measurement_id"] = (
                    stream.web_stream_data.measurement_id
                )

            result.append(item)

        return {
            "property_id": self.property_id,
            "stream_count": len(result),
            "streams": result,
        }    

        
    def get_stream_data(self):
        """Fetch GA4 stream configuration metadata."""
        admin_client = AnalyticsAdminServiceClient(
            credentials=self.credentials
        )

        streams = admin_client.list_data_streams(
            parent=f"properties/{self.property_id}"
        )

        result = []

        for stream in streams:
            item = {
                "stream_name": stream.display_name,
                "stream_id": stream.name.rsplit("/", 1)[-1],
                "stream_type": str(stream.type_),
            }

            if stream.web_stream_data:
                item["website_url"] = (
                    stream.web_stream_data.default_uri
                )
                item["measurement_id"] = (
                    stream.web_stream_data.measurement_id
                )

            result.append(item)

        return {
            "property_id": self.property_id,
            "stream_count": len(result),
            "streams": result,
        }

    
    def get_realtime_stream_data(self):
        """Fetch realtime active users and event counts separately."""

        client = self.client
        property_name = f"properties/{self.property_id}"

        def fetch_realtime(dimension_name, metric_name):
            request = RunRealtimeReportRequest(
                property=property_name,
                dimensions=[Dimension(name=dimension_name)],
                metrics=[Metric(name=metric_name)],
                limit=100,
            )

            response = client.run_realtime_report(request)

            return [
                {
                    dimension_name: row.dimension_values[0].value,
                    metric_name: int(row.metric_values[0].value),
                }
                for row in response.rows
            ]

        try:
           event_data = fetch_realtime("eventName", "eventCount")
        except Exception as error:
           event_data = {"error": str(error)}

        try:
           user_data = fetch_realtime("unifiedScreenName", "activeUsers")
        except Exception:
           # Fall back to a realtime metric without a dimension.
           try:
                request = RunRealtimeReportRequest(
                   property=property_name,
                   metrics=[Metric(name="activeUsers")],
                )
                response = client.run_realtime_report(request)
                user_data = {
                    "activeUsers": int(
                        response.rows[0].metric_values[0].value
                    ) if response.rows else 0
                }
           except Exception as error:
               user_data = {"error": str(error)}

        return {
            "property_id": self.property_id,
            "report_type": "realtime_stream",
            "events": event_data,
            "users": user_data,
        }


    def _run_report(
        self,
        start_date,
        end_date,
        dimensions,
        metrics,
        limit=100,
    ):
        request = RunReportRequest(
            property=f"properties/{self.property_id}",
            date_ranges=[
                DateRange(
                    start_date=start_date,
                    end_date=end_date,
                )
            ],
            dimensions=[
                Dimension(name=name) for name in dimensions
            ],
            metrics=[
                Metric(name=name) for name in metrics
            ],
            limit=limit,
        )

        response = self.client.run_report(request)

        rows = []

        for row in response.rows:
            result = {}

            for index, name in enumerate(dimensions):
                result[name] = (
                    row.dimension_values[index].value
                )

            for index, name in enumerate(metrics):
                raw_value = row.metric_values[index].value

                try:
                    result[name] = (
                        float(raw_value)
                        if "." in raw_value
                        else int(raw_value)
                    )
                except (ValueError, TypeError):
                    result[name] = raw_value

            rows.append(result)

        return {
            "row_count": response.row_count,
            "rows_returned": len(rows),
            "rows": rows,
        }



    def get_overview(
        self,
        start_date="7daysAgo",
        end_date="yesterday",
    ):
        return self._run_report(
            start_date=start_date,
            end_date=end_date,
            dimensions=[],
            metrics=[
                "activeUsers",
                "newUsers",
                "sessions",
                "screenPageViews",
                "engagedSessions",
                "conversions",
            ],
            limit=1,
        )

    def get_traffic_sources(
        self,
        start_date="7daysAgo",
        end_date="yesterday",
        limit=20,
    ):
        return self._run_report(
            start_date=start_date,
            end_date=end_date,
            dimensions=[
                "sessionDefaultChannelGroup"
            ],
            metrics=[
                "sessions",
                "activeUsers",
                "conversions",
            ],
            limit=limit,
        )

    
    def get_top_pages(
        self,
        start_date="7daysAgo",
        end_date="yesterday",
        limit=20,
    ):
        """Fetch page views, users, engagement, bounce rate and conversions."""
        return self._run_report(
            start_date=start_date,
            end_date=end_date,
            dimensions=["pagePath"],
            metrics=[
                "screenPageViews",
                "activeUsers",
                "engagementRate",
                "bounceRate",
                "conversions",
            ],
            limit=limit,
        )

    
    def get_traffic_by_date(
        self, start_date="7daysAgo", end_date="yesterday"
    ):
        """Daily visitors, sessions, views and engagement."""
        return self._run_report(
            start_date, end_date,
            dimensions=["date"],
            metrics=[
                "activeUsers",
                "newUsers",
                "totalUsers",
                "sessions",
                "screenPageViews",
                "engagedSessions",
                "engagementRate",
           
            ],
            limit=100,
        )

    def get_traffic_by_hour(
        self, start_date="7daysAgo", end_date="yesterday"
    ):
        """Traffic grouped by date and hour."""
        return self._run_report(
            start_date, end_date,
            dimensions=["date", "hour"],
            metrics=[
                "activeUsers",
                "sessions",
                "screenPageViews",
                "engagedSessions",
            ],
            limit=1000,
        )

    def get_detailed_traffic_sources(
        self, start_date="7daysAgo",
        end_date="yesterday", limit=100
    ):
        """Traffic source, medium, channel and campaign."""
        return self._run_report(
            start_date, end_date,
            dimensions=[
                "sessionDefaultChannelGroup",
                "sessionSource",
                "sessionMedium",
                "sessionCampaignName",
            ],
            metrics=[
                "sessions",
                "totalUsers",
                "newUsers",
                "engagedSessions",
                "conversions",
            ],
            limit=limit,
        )

    def get_landing_pages(
        self, start_date="7daysAgo",
        end_date="yesterday", limit=100
    ):
        """Landing-page performance and engagement."""
        return self._run_report(
            start_date, end_date,
            dimensions=["landingPagePlusQueryString"],
            metrics=[
                "sessions",
                "activeUsers",
                "newUsers",
                "engagedSessions",
                "engagementRate",
                 "conversions",
            ],
            limit=limit,
        )

    def get_device_technology(
        self, start_date="7daysAgo",
        end_date="yesterday", limit=100
    ):
        """Device category, browser and operating system."""
        return self._run_report(
            start_date, end_date,
            dimensions=[
                "deviceCategory",
                "browser",
                "operatingSystem",
            ],
            metrics=[
                "activeUsers",
                "sessions",
                "screenPageViews",
                "engagedSessions",
            ],
            limit=limit,
        )
    
    
    
    def get_period_comparison(self, start_date, end_date):
        """Compare selected dates with the previous equal-length period."""
        from datetime import date, timedelta

        try:
            current_start = date.fromisoformat(start_date)
            current_end = date.fromisoformat(end_date)
        except (ValueError, TypeError):
            raise ValueError(
                "Period comparison requires YYYY-MM-DD dates."
            )

        if current_start > current_end:
            raise ValueError(
                "start_date must be earlier than or equal to end_date."
            )

        period_days = (current_end - current_start).days + 1

        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(
            days=period_days - 1
        )

        metrics = [
            "activeUsers",
            "newUsers",
            "sessions",
            "screenPageViews",
            "engagedSessions",
            "conversions",
        ]

        current = self._run_report(
            start_date=current_start.isoformat(),
            end_date=current_end.isoformat(),
            dimensions=[],
            metrics=metrics,
            limit=1,
        )

        previous = self._run_report(
            start_date=previous_start.isoformat(),
            end_date=previous_end.isoformat(),
            dimensions=[],
            metrics=metrics,
            limit=1,
        )

        current_row = current["rows"][0] if current["rows"] else {}
        previous_row = previous["rows"][0] if previous["rows"] else {}

        current_available = bool(current["rows"])
        previous_available = bool(previous["rows"])

        comparison = {}

        for metric in metrics:
            current_value = current_row.get(metric)
            previous_value = previous_row.get(metric)

            if current_value is None or previous_value is None:
                comparison[metric] = {
                    "current": current_value,
                    "previous": previous_value,
                    "difference": None,
                    "percentage_change": None,
                    "status": "no_data",
                }
                continue

            difference = current_value - previous_value

            if previous_value == 0:
                percentage_change = (
                    0.0 if current_value == 0 else None
                )
            else:
                percentage_change = round(
                    difference / previous_value * 100, 2
                )

            comparison[metric] = {
                "current": current_value,
                "previous": previous_value,
                "difference": difference,
                "percentage_change": percentage_change,
                "status": (
                    "increased" if difference > 0
                    else "decreased" if difference < 0
                    else "unchanged"
                ),
            }

        if current_available and previous_available:
            data_status = "data_available"
        elif current_available or previous_available:
            data_status = "partial_data"
        else:
            data_status = "no_data"

        return {
            "current_period": {
                "start_date": current_start.isoformat(),
                "end_date": current_end.isoformat(),
            },
            "previous_period": {
                "start_date": previous_start.isoformat(),
                "end_date": previous_end.isoformat(),
            },
            "period_days": period_days,
            "data_status": data_status,
            "comparison": comparison,
        }
