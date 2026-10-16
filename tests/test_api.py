from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.storage import DemoStore


FIXED_NOW = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def store():
    return DemoStore(clock=lambda: FIXED_NOW)


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


def role(role_name, user_id):
    return {"X-Demo-Role": role_name, "X-Demo-User": user_id}


def valid_donation(**overrides):
    prepared = FIXED_NOW - timedelta(minutes=30)
    deadline = FIXED_NOW + timedelta(hours=3)
    data = {
        "title": "Fresh lentil bowls",
        "category": "Prepared Meals",
        "description": "Sealed demo meal portions.",
        "quantity": 24,
        "unit": "portions",
        "prepared_at": prepared.isoformat(),
        "pickup_deadline": deadline.isoformat(),
        "donor_confirms_edible": True,
        "storage_conditions": "Covered and refrigerated while awaiting pickup.",
        "allergens": ["milk"],
        "allergen_info_known": True,
        "location": "Demo College Campus, Demo City",
        "latitude": 12.9716,
        "longitude": 77.5946,
    }
    return {**data, **overrides}


def test_health_status_and_frontend_are_served(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    status = client.get("/api/status").json()
    assert status["mode"] == "demo"
    assert "in-memory" in status["storage"]
    assert client.get("/").status_code == 200
    assert "FoodLoop" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_valid_donation_is_created(client):
    response = client.post(
        "/api/donations",
        headers=role("donor", "demo-canteen"),
        json=valid_donation(),
    )
    assert response.status_code == 201
    assert response.json()["safety_status"] == "ELIGIBLE"
    assert response.json()["status"] == "AVAILABLE"


def test_listing_filters_detail_claim_list_and_demo_auth(client):
    donations = client.get("/api/donations?search=rice&category=Prepared%20Meals").json()
    assert [item["id"] for item in donations] == ["demo-meals-30"]
    detail = client.get("/api/donations/demo-meals-30").json()
    assert detail["quantity"] == 30
    assert client.get("/api/auth/me", headers=role("recipient", "org-harvest")).json() == {
        "role": "recipient",
        "identity": "org-harvest",
    }
    login = client.post("/api/auth/login", json={"email": "judge@example.test", "password": "not-a-real-password"})
    assert login.status_code == 400
    claim = client.post(
        "/api/donations/demo-meals-30/claims",
        headers=role("recipient", "org-harvest"),
        json={"recipient_id": "org-harvest", "requested_quantity": 10},
    )
    assert claim.status_code == 201
    claim_rows = client.get("/api/claims", headers=role("recipient", "org-harvest")).json()
    assert len(claim_rows) == 2
    assert any(row["status"] == "REQUESTED" for row in claim_rows)
    assert any(row["donation_title"] == "Fresh vegetable rice bowls" for row in claim_rows)


def test_invalid_quantity_and_past_deadline_are_rejected(client):
    invalid_quantity = client.post(
        "/api/donations",
        headers=role("donor", "demo-canteen"),
        json=valid_donation(quantity=0),
    )
    assert invalid_quantity.status_code == 422

    past = (FIXED_NOW - timedelta(hours=1)).isoformat()
    past_deadline = client.post(
        "/api/donations",
        headers=role("donor", "demo-canteen"),
        json=valid_donation(
            prepared_at=(FIXED_NOW - timedelta(hours=2)).isoformat(),
            pickup_deadline=past,
        ),
    )
    assert past_deadline.status_code == 422
    assert "future" in past_deadline.json()["detail"].lower()


def test_donation_not_confirmed_as_edible_is_rejected(client):
    response = client.post(
        "/api/donations",
        headers=role("donor", "demo-canteen"),
        json=valid_donation(donor_confirms_edible=False),
    )
    assert response.status_code == 422
    assert "edible" in response.json()["detail"]


def test_missing_allergen_information_requires_review_and_cannot_be_claimed(client):
    created = client.post(
        "/api/donations",
        headers=role("donor", "demo-canteen"),
        json=valid_donation(allergen_info_known=False, allergens=[]),
    ).json()
    assert created["safety_status"] == "PENDING_REVIEW"
    assert any("Allergen" in message for message in created["safety_warnings"])
    claim = client.post(
        f"/api/donations/{created['id']}/claims",
        headers=role("recipient", "org-harvest"),
        json={"recipient_id": "org-harvest", "requested_quantity": 10},
    )
    assert claim.status_code == 409


def test_claim_checks_pickup_window_and_recipient_category(client, store):
    short_window = client.post(
        "/api/donations",
        headers=role("donor", "demo-canteen"),
        json=valid_donation(pickup_deadline=(FIXED_NOW + timedelta(minutes=20)).isoformat()),
    ).json()
    too_late = client.post(
        f"/api/donations/{short_window['id']}/claims",
        headers=role("recipient", "org-harvest"),
        json={"recipient_id": "org-harvest", "requested_quantity": 10},
    )
    assert too_late.status_code == 409
    assert "pickup window" in too_late.json()["error"]

    store.get_recipient("org-harvest")["preferred_categories"] = ["Bakery"]
    store.recipients[0]["preferred_categories"] = ["Bakery"]
    category_rejected = client.post(
        "/api/donations/demo-meals-30/claims",
        headers=role("recipient", "org-harvest"),
        json={"recipient_id": "org-harvest", "requested_quantity": 10},
    )
    assert category_rejected.status_code == 409
    assert "category" in category_rejected.json()["error"]


def test_expired_and_unverified_claims_are_rejected(client):
    expired = client.post(
        "/api/donations/demo-expired-listing/claims",
        headers=role("recipient", "org-harvest"),
        json={"recipient_id": "org-harvest", "requested_quantity": 10},
    )
    assert expired.status_code == 409

    unverified = client.post(
        "/api/donations/demo-meals-30/claims",
        headers=role("recipient", "org-review"),
        json={"recipient_id": "org-review", "requested_quantity": 10},
    )
    assert unverified.status_code == 403


def test_matching_ranks_eligible_recipients_and_does_not_fabricate_distance(client):
    matches = client.get("/api/donations/demo-meals-30/matches").json()["matches"]
    eligible = [item for item in matches if item["eligible"]]
    assert eligible[0]["recipient_id"] == "org-neighborhood"
    no_coordinates = next(item for item in eligible if item["recipient_id"] == "org-community")
    assert no_coordinates["component_scores"]["distance"] is None
    assert any("Distance unavailable" in reason for reason in no_coordinates["reasons"])
    assert not any(" km away" in reason for reason in no_coordinates["reasons"])
    assert all(item["score"] <= 100 for item in matches)


def test_quantity_mismatch_excludes_recipients(client, store):
    donation = store.get_donation("demo-meals-30")
    donation["quantity"] = 3
    store.donations[donation["id"]] = donation
    matches = client.get("/api/donations/demo-meals-30/matches").json()["matches"]
    assert all(not item["eligible"] for item in matches)


def test_concurrent_claims_cannot_reserve_a_donation_twice(client):
    def make_claim(organization):
        return client.post(
            "/api/donations/demo-meals-30/claims",
            headers=role("recipient", organization),
            json={"recipient_id": organization, "requested_quantity": 10},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(make_claim, ["org-harvest", "org-neighborhood"]))
    assert sorted(response.status_code for response in responses) == [201, 409]


def test_workflow_requires_valid_transitions_and_completion_updates_impact(client):
    claim = client.post(
        "/api/donations/demo-meals-30/claims",
        headers=role("recipient", "org-harvest"),
        json={"recipient_id": "org-harvest", "requested_quantity": 30},
    ).json()
    wrong_actor = client.patch(
        f"/api/claims/{claim['id']}/status",
        headers=role("recipient", "org-harvest"),
        json={"status": "ACCEPTED"},
    )
    assert wrong_actor.status_code == 403

    donor = role("donor", "demo-canteen")
    assert client.patch(
        f"/api/claims/{claim['id']}/status", headers=donor, json={"status": "ACCEPTED"}
    ).status_code == 200
    assert client.patch(
        f"/api/claims/{claim['id']}/status", headers=donor, json={"status": "READY_FOR_PICKUP"}
    ).status_code == 200
    admin_completion = client.patch(
        f"/api/claims/{claim['id']}/status",
        headers=role("admin", "demo-admin"),
        json={"status": "COMPLETED"},
    )
    assert admin_completion.status_code == 403
    complete = client.patch(
        f"/api/claims/{claim['id']}/status",
        headers=role("recipient", "org-harvest"),
        json={"status": "COMPLETED"},
    )
    assert complete.status_code == 200
    assert complete.json()["completed_at"]

    impact = client.get("/api/impact").json()
    assert impact["completed_donations"] == 2
    assert impact["portions_donated"] == 50
    assert impact["estimated_food_waste_avoided_kg"] == 20
    assert impact["demo_data"] is True

    duplicate_completion = client.patch(
        f"/api/claims/{claim['id']}/status",
        headers=role("recipient", "org-harvest"),
        json={"status": "COMPLETED"},
    )
    assert duplicate_completion.status_code == 403


def test_admin_review_and_authorization(client):
    denied = client.get("/api/admin/reviews", headers=role("donor", "demo-canteen"))
    assert denied.status_code == 403
    review = client.get("/api/admin/reviews", headers=role("admin", "demo-admin"))
    assert review.status_code == 200
    assert any(row["id"] == "demo-review-listing" for row in review.json()["safety_reviews"])
    resolved = client.patch(
        "/api/admin/donations/demo-review-listing/review",
        headers=role("admin", "demo-admin"),
        json={"action": "resolve", "note": "Human review completed for the demo."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["safety_status"] == "ELIGIBLE"


def test_admin_can_verify_an_organization(client):
    response = client.patch(
        "/api/admin/organizations/org-review/verify",
        headers=role("admin", "demo-admin"),
    )
    assert response.status_code == 200
    assert response.json()["verification_status"] == "VERIFIED"


def test_safety_flag_stops_claim_progress_until_cancelled(client):
    claim = client.post(
        "/api/donations/demo-meals-30/claims",
        headers=role("recipient", "org-harvest"),
        json={"recipient_id": "org-harvest", "requested_quantity": 10},
    ).json()
    flagged = client.patch(
        "/api/admin/donations/demo-meals-30/review",
        headers=role("admin", "demo-admin"),
        json={"action": "flag", "note": "Review handling details."},
    )
    assert flagged.status_code == 200
    progression = client.patch(
        f"/api/claims/{claim['id']}/status",
        headers=role("donor", "demo-canteen"),
        json={"status": "ACCEPTED"},
    )
    assert progression.status_code == 409
    withdrawal = client.patch(
        "/api/admin/donations/demo-meals-30/review",
        headers=role("admin", "demo-admin"),
        json={"action": "withdraw"},
    )
    assert withdrawal.status_code == 409
    cancelled = client.patch(
        f"/api/claims/{claim['id']}/status",
        headers=role("recipient", "org-harvest"),
        json={"status": "CANCELLED"},
    )
    assert cancelled.status_code == 200
    withdrawn = client.patch(
        "/api/admin/donations/demo-meals-30/review",
        headers=role("admin", "demo-admin"),
        json={"action": "withdraw"},
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "WITHDRAWN"


def test_api_failures_are_clean_json(client):
    response = client.get("/api/donations/not-a-real-donation")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"error": "Donation not found."}
