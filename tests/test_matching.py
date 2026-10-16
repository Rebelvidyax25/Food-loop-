from datetime import datetime, timedelta, timezone

from backend.matching import rank_recipients
from backend.seed_data import make_seed_data


def test_matching_is_deterministic_and_scores_nearer_locations_higher():
    now = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
    seed = make_seed_data(now)
    donation = next(row for row in seed["donations"] if row["id"] == "demo-meals-30")
    first = rank_recipients(donation, seed["recipients"], now)
    second = rank_recipients(donation, seed["recipients"], now)
    assert first == second
    assert first[0]["recipient_id"] == "org-neighborhood"
    assert first[0]["eligible"] is True
    assert set(first[0]["component_scores"]) == {"distance", "urgency", "quantity", "availability"}


def test_unverified_and_out_of_window_recipients_are_excluded():
    now = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
    seed = make_seed_data(now)
    donation = next(row for row in seed["donations"] if row["id"] == "demo-meals-30")
    donation["pickup_deadline"] = (now + timedelta(minutes=15)).isoformat()
    recipients = seed["recipients"]
    matches = rank_recipients(donation, recipients, now)
    by_id = {item["recipient_id"]: item for item in matches}
    assert by_id["org-review"]["eligible"] is False
    assert by_id["org-community"]["eligible"] is False
    assert any("pickup window" in reason for reason in by_id["org-community"]["reasons"])


def test_quantity_requirement_blocks_a_too_small_donation():
    now = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
    seed = make_seed_data(now)
    donation = next(row for row in seed["donations"] if row["id"] == "demo-meals-30")
    donation["quantity"] = 2
    matches = rank_recipients(donation, seed["recipients"], now)
    assert not any(item["eligible"] for item in matches)
    harvest = next(item for item in matches if item["recipient_id"] == "org-harvest")
    assert harvest["component_scores"]["quantity"] == 0
