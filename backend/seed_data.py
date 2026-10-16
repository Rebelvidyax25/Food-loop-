from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .models import Donor, DonationClaim, FoodDonation, RecipientOrganization


def _time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def make_seed_data(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    donor_ids = ["demo-canteen", "demo-events"]
    recipients = [
        {
            "id": "org-harvest",
            "name": "Demo Harvest Community Kitchen",
            "verification_status": "VERIFIED",
            "preferred_categories": ["Prepared Meals", "Produce", "Bakery"],
            "minimum_quantity": 5,
            "maximum_quantity": 100,
            "available": True,
            "pickup_capacity": 80,
            "location": "Demo District North",
            "latitude": 12.975,
            "longitude": 77.605,
            "estimated_pickup_minutes": 35,
        },
        {
            "id": "org-neighborhood",
            "name": "Demo Neighborhood Pantry",
            "verification_status": "VERIFIED",
            "preferred_categories": ["Prepared Meals", "Bakery"],
            "minimum_quantity": 10,
            "maximum_quantity": 50,
            "available": True,
            "pickup_capacity": 50,
            "location": "Demo District Central",
            "latitude": 12.968,
            "longitude": 77.59,
            "estimated_pickup_minutes": 20,
        },
        {
            "id": "org-community",
            "name": "Demo Community Outreach",
            "verification_status": "VERIFIED",
            "preferred_categories": ["Produce", "Prepared Meals"],
            "minimum_quantity": 15,
            "maximum_quantity": 120,
            "available": True,
            "pickup_capacity": 120,
            "location": "Demo District East",
            "latitude": None,
            "longitude": None,
            "estimated_pickup_minutes": 55,
        },
        {
            "id": "org-review",
            "name": "Demo Organization Awaiting Review",
            "verification_status": "PENDING",
            "preferred_categories": ["Prepared Meals", "Produce"],
            "minimum_quantity": 1,
            "maximum_quantity": 100,
            "available": True,
            "pickup_capacity": 100,
            "location": "Demo District South",
            "latitude": 12.95,
            "longitude": 77.58,
            "estimated_pickup_minutes": 25,
        },
    ]
    donations = []
    for donation_id, donor_id, title, quantity, category, status, offset in [
        ("demo-meals-30", donor_ids[0], "Fresh vegetable rice bowls", 30, "Prepared Meals", "AVAILABLE", 4),
        ("demo-produce-40", donor_ids[1], "Seasonal fruit and vegetables", 40, "Produce", "AVAILABLE", 8),
        ("demo-review-listing", donor_ids[0], "Assorted baked goods", 18, "Bakery", "AVAILABLE", 6),
        ("demo-expired-listing", donor_ids[1], "Event snack boxes", 24, "Prepared Meals", "EXPIRED", -1),
        ("demo-completed-listing", donor_ids[0], "Completed demo meal donation", 20, "Prepared Meals", "COMPLETED", 48),
    ]:
        preparation_age_hours = (
            26 if status == "COMPLETED" else 4 if status == "EXPIRED" else 2
        )
        prepared = now - timedelta(hours=preparation_age_hours)
        deadline = now + timedelta(hours=offset)
        if offset < 0:
            deadline = now - timedelta(hours=2)
        if status == "COMPLETED":
            deadline = now - timedelta(hours=24)
        review = status == "AVAILABLE" and donation_id == "demo-review-listing"
        created_at = (
            now - timedelta(hours=26) if status == "COMPLETED"
            else now - timedelta(hours=3)
        )
        updated_at = (
            now - timedelta(hours=24) if status == "COMPLETED" else created_at
        )
        donations.append(
            {
                "id": donation_id,
                "donor_id": donor_id,
                "donor_name": "Demo College Canteen" if donor_id == donor_ids[0] else "Demo Event Organizer",
                "title": title,
                "category": category,
                "description": "Synthetic sample listing for a FoodLoop demonstration.",
                "quantity": quantity,
                "unit": "portions",
                "prepared_at": _time(prepared),
                "pickup_deadline": _time(deadline),
                "storage_conditions": "Kept covered under refrigeration; storage details are demonstration text.",
                "allergens": ["gluten"] if category == "Prepared Meals" else [],
                "allergen_info_known": True,
                "location": "Demo College Campus, Demo City",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "minimum_quantity": None,
                "maximum_quantity": None,
                "status": status,
                "safety_status": (
                    "EXPIRED" if status == "EXPIRED"
                    else "PENDING_REVIEW" if review
                    else "ELIGIBLE"
                ),
                "safety_warnings": (
                    ["Sample listing awaiting a human safety review."]
                    if review
                    else ["Pickup deadline has passed."]
                    if status == "EXPIRED"
                    else []
                ),
                "review_note": None,
                "created_at": _time(created_at),
                "updated_at": _time(updated_at),
            }
        )
    claims = [
        {
            "id": "demo-completed-claim",
            "donation_id": "demo-completed-listing",
            "recipient_id": "org-harvest",
            "requested_quantity": 20,
            "status": "COMPLETED",
            "created_at": _time(now - timedelta(hours=26)),
            "updated_at": _time(now - timedelta(hours=24)),
            "completed_at": _time(now - timedelta(hours=24)),
        }
    ]
    donor_records = [
        Donor(id=donor_ids[0], display_name="Demo College Canteen").model_dump(mode="json"),
        Donor(id=donor_ids[1], display_name="Demo Event Organizer").model_dump(mode="json"),
    ]
    return {
        "donors": donor_records,
        "recipients": [
            RecipientOrganization.model_validate(row).model_dump(mode="json")
            for row in recipients
        ],
        "donations": [
            FoodDonation.model_validate(
                {**row, "donor_confirms_edible": True}
            ).model_dump(mode="json")
            for row in donations
        ],
        "claims": [
            DonationClaim.model_validate(row).model_dump(mode="json")
            for row in claims
        ],
        "request_id_factory": uuid4,
    }
