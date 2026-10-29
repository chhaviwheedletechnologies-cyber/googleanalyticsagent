import os
from datetime import datetime, timezone

from pymongo import MongoClient


def save_report(report):
    mongo_uri = os.getenv("MONGODB_URI", "").strip()

    if not mongo_uri:
        return {
            "saved": False,
            "message": "MongoDB is not configured",
        }

    database_name = os.getenv(
        "MONGODB_DATABASE",
        "google_analytics_agent",
    )

    collection_name = os.getenv(
        "MONGODB_COLLECTION",
        "reports",
    )

    client = MongoClient(
        mongo_uri,
        serverSelectionTimeoutMS=3000,
    )

    try:
        collection = client[database_name][collection_name]

        document = dict(report)
        document["stored_at"] = datetime.now(timezone.utc)

        result = collection.insert_one(document)

        return {
            "saved": True,
            "id": str(result.inserted_id),
        }

    finally:
        client.close()