from datetime import datetime, timedelta, timezone

from backend.safety import assess_safety


def sample_donation(now):
    return {
        "category": "Prepared Meals",
        "quantity": 12,
        "donor_confirms_edible": True,
        "prepared_at": now - timedelta(hours=1),
        "pickup_deadline": now + timedelta(hours=2),
        "storage_conditions": "Covered and refrigerated.",
        "allergen_info_known": True,
    }


def test_complete_safety_information_is_eligible():
    now = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
    result = assess_safety(sample_donation(now), now)
    assert result == {"status": "ELIGIBLE", "warnings": []}


def test_unknown_allergens_or_incomplete_storage_require_review():
    now = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
    donation = sample_donation(now)
    donation["allergen_info_known"] = False
    donation["storage_conditions"] = "Cold"
    result = assess_safety(donation, now)
    assert result["status"] == "PENDING_REVIEW"
    assert len(result["warnings"]) == 2


def test_questionable_storage_information_requires_human_review():
    now = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
    donation = sample_donation(now)
    donation["storage_conditions"] = "Left out at room temperature."
    result = assess_safety(donation, now)
    assert result["status"] == "PENDING_REVIEW"
    assert any("human safety review" in warning for warning in result["warnings"])


def test_expired_listing_is_not_eligible():
    now = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
    donation = sample_donation(now)
    donation["pickup_deadline"] = now - timedelta(minutes=1)
    result = assess_safety(donation, now)
    assert result["status"] == "EXPIRED"
    assert any("passed" in warning for warning in result["warnings"])
