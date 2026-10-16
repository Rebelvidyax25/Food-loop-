from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt


WEIGHTS = {"distance": 35, "urgency": 25, "quantity": 25, "availability": 15}
MAX_DISTANCE_KM = 50


def _distance_km(first: dict, second: dict) -> float | None:
    coordinates = ("latitude", "longitude")
    if any(first.get(key) is None or second.get(key) is None for key in coordinates):
        return None
    lat1, lon1, lat2, lon2 = map(
        radians,
        (first["latitude"], first["longitude"], second["latitude"], second["longitude"]),
    )
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 6371 * 2 * asin(sqrt(value))


def rank_recipients(donation: dict, recipients: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    deadline = datetime.fromisoformat(donation["pickup_deadline"])
    remaining_hours = (deadline - now).total_seconds() / 3600
    urgency = max(0, min(100, round(100 - remaining_hours / 24 * 100)))
    matches = []

    for recipient in recipients:
        reasons = []
        active = (
            recipient.get("verification_status") == "VERIFIED"
            and recipient.get("available", False)
        )
        lower_bound = max(
            recipient.get("minimum_quantity", 0),
            donation.get("minimum_quantity") or 0,
        )
        upper_bound = min(
            recipient.get("maximum_quantity", float("inf")),
            donation.get("maximum_quantity") or float("inf"),
            donation["quantity"],
        )
        quantity_ok = lower_bound <= upper_bound and recipient.get("pickup_capacity", 0) >= lower_bound
        pickup_ok = recipient.get("estimated_pickup_minutes", 10**9) < remaining_hours * 60
        category_ok = not recipient.get("preferred_categories") or donation["category"] in recipient["preferred_categories"]
        eligible = active and quantity_ok and pickup_ok and category_ok
        if not active:
            reasons.append("Organization is not verified and available.")
        if not quantity_ok:
            reasons.append("Organization quantity or pickup capacity does not fit.")
        if not pickup_ok:
            reasons.append("Estimated pickup is outside the safe pickup window.")
        if not category_ok:
            reasons.append("Food category is outside the organization's preferences.")

        distance = _distance_km(donation, recipient)
        distance_score = None if distance is None else max(0, round(100 * (1 - distance / MAX_DISTANCE_KM)))
        quantity_score = 100 if quantity_ok else 0
        availability_score = 100 if active and pickup_ok else 0
        scores = {
            "distance": distance_score,
            "urgency": urgency,
            "quantity": quantity_score,
            "availability": availability_score,
        }
        # Missing coordinates are neutral, not a made-up distance or score.
        weighted = sum(
            WEIGHTS[key] * (scores[key] if scores[key] is not None else 50)
            for key in WEIGHTS
        ) / sum(WEIGHTS.values())
        if eligible:
            if distance is None:
                reasons.append("Distance unavailable; location text is shown without an estimate.")
            else:
                reasons.append(f"Pickup location is approximately {distance:.1f} km away (straight-line estimate).")
            reasons.append("Quantity, verification, and pickup window are suitable.")
        matches.append(
            {
                "recipient_id": recipient["id"],
                "organization_name": recipient["name"],
                "score": round(weighted) if eligible else 0,
                "component_scores": scores,
                "eligible": eligible,
                "reasons": reasons,
                "_distance_km": distance,
            }
        )
    ranked = sorted(
        matches,
        key=lambda match: (
            match["eligible"],
            match["score"],
            match["_distance_km"] is not None,
            -(match["_distance_km"] or 0),
        ),
        reverse=True,
    )
    for match in ranked:
        del match["_distance_km"]
    return ranked
