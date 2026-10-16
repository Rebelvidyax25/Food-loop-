import os
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from .models import (
    ClaimStatus,
    DonationClaim,
    DonationStatus,
    FoodDonation,
    SafetyStatus,
)
from .seed_data import make_seed_data


ACTIVE_CLAIM_STATUSES = {
    ClaimStatus.REQUESTED.value,
    ClaimStatus.ACCEPTED.value,
    ClaimStatus.READY_FOR_PICKUP.value,
}


class DemoStore:
    """Thread-safe in-process repository for the clearly labelled demo mode."""

    mode = "in-memory demo"

    def __init__(self, clock=None):
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        seed = make_seed_data(self.clock())
        self.donors = {row["id"]: row for row in seed["donors"]}
        self.recipients = seed["recipients"]
        self.donations = {row["id"]: row for row in seed["donations"]}
        self.claims = {row["id"]: row for row in seed["claims"]}
        self._new_id = seed["request_id_factory"]
        self._lock = RLock()

    def now(self) -> datetime:
        return self.clock().astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    def _expire(self, donation: dict) -> None:
        if donation["status"] == DonationStatus.AVAILABLE.value:
            deadline = datetime.fromisoformat(donation["pickup_deadline"])
            if deadline <= self.now():
                donation["status"] = DonationStatus.EXPIRED.value
                donation["safety_status"] = SafetyStatus.EXPIRED.value
                donation["safety_warnings"] = list(donation.get("safety_warnings", []))
                if "Pickup deadline has passed." not in donation["safety_warnings"]:
                    donation["safety_warnings"].append("Pickup deadline has passed.")
                donation["updated_at"] = self._iso(self.now())

    def list_donations(self) -> list[dict]:
        with self._lock:
            for donation in self.donations.values():
                self._expire(donation)
            return [dict(row) for row in self.donations.values()]

    def get_donation(self, donation_id: str) -> dict | None:
        with self._lock:
            donation = self.donations.get(donation_id)
            if donation is not None:
                self._expire(donation)
                return dict(donation)
            return None

    def list_recipients(self) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self.recipients]

    def get_recipient(self, recipient_id: str) -> dict | None:
        with self._lock:
            row = next((r for r in self.recipients if r["id"] == recipient_id), None)
            return dict(row) if row else None

    def get_donor_name(self, donor_id: str) -> str:
        return self.donors.get(donor_id, {}).get("display_name", "Demo Donor")

    def list_claims(self) -> list[dict]:
        with self._lock:
            for claim in self.claims.values():
                if claim["status"] in ACTIVE_CLAIM_STATUSES:
                    donation = self.donations[claim["donation_id"]]
                    deadline = datetime.fromisoformat(donation["pickup_deadline"])
                    if deadline <= self.now():
                        donation["status"] = DonationStatus.EXPIRED.value
                        donation["safety_status"] = SafetyStatus.EXPIRED.value
                        donation["safety_warnings"] = list(donation.get("safety_warnings", []))
                        if "Pickup deadline has passed." not in donation["safety_warnings"]:
                            donation["safety_warnings"].append("Pickup deadline has passed.")
                        donation["updated_at"] = self._iso(self.now())
            return [dict(row) for row in self.claims.values()]

    def get_claim(self, claim_id: str) -> dict | None:
        with self._lock:
            row = self.claims.get(claim_id)
            return dict(row) if row else None

    def create_donation(self, donation: dict, donor_id: str) -> dict:
        with self._lock:
            now = self._iso(self.now())
            record = {
                **donation,
                "id": f"donation-{self._new_id().hex[:12]}",
                "donor_id": donor_id,
                "donor_name": self.get_donor_name(donor_id),
                "status": DonationStatus.AVAILABLE.value,
                "created_at": now,
                "updated_at": now,
            }
            self.donations[record["id"]] = record
            return dict(record)

    def request_claim(self, donation_id: str, recipient_id: str, quantity: float) -> dict:
        with self._lock:
            donation = self.donations.get(donation_id)
            recipient = next((r for r in self.recipients if r["id"] == recipient_id), None)
            if donation is None:
                raise LookupError("Donation not found.")
            self._expire(donation)
            if recipient is None:
                raise LookupError("Recipient organization not found.")
            if recipient["verification_status"] != "VERIFIED":
                raise PermissionError("Only verified organizations may request donations.")
            if not recipient.get("available"):
                raise PermissionError("This organization is not currently available for pickup.")
            if donation["status"] != DonationStatus.AVAILABLE.value:
                raise ValueError("This donation is no longer available.")
            if donation.get("safety_status") != SafetyStatus.ELIGIBLE.value:
                raise ValueError("This donation is not cleared for pickup.")
            deadline = datetime.fromisoformat(donation["pickup_deadline"])
            if deadline <= self.now():
                self._expire(donation)
                raise ValueError("This donation's pickup deadline has passed.")
            if (
                recipient.get("preferred_categories")
                and donation["category"] not in recipient["preferred_categories"]
            ):
                raise ValueError("This organization does not accept this food category.")
            remaining_minutes = (deadline - self.now()).total_seconds() / 60
            if recipient["estimated_pickup_minutes"] >= remaining_minutes:
                raise ValueError("This organization cannot collect within the pickup window.")
            if quantity > donation["quantity"] or quantity > recipient["pickup_capacity"]:
                raise ValueError("Requested quantity exceeds the available donation or pickup capacity.")
            if quantity < recipient["minimum_quantity"] or quantity > recipient["maximum_quantity"]:
                raise ValueError("Requested quantity is outside the organization's accepted range.")
            if donation.get("minimum_quantity") and quantity < donation["minimum_quantity"]:
                raise ValueError("Requested quantity is below the donor's minimum.")
            if donation.get("maximum_quantity") and quantity > donation["maximum_quantity"]:
                raise ValueError("Requested quantity exceeds the donor's maximum.")
            now = self._iso(self.now())
            claim = DonationClaim.model_validate({
                "id": f"claim-{self._new_id().hex[:12]}",
                "donation_id": donation_id,
                "recipient_id": recipient_id,
                "requested_quantity": quantity,
                "status": ClaimStatus.REQUESTED.value,
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
            }).model_dump(mode="json")
            self.claims[claim["id"]] = claim
            donation["status"] = DonationStatus.REQUESTED.value
            donation["updated_at"] = now
            return dict(claim)

    def transition_claim(self, claim_id: str, new_status: str, actor: dict) -> dict:
        with self._lock:
            claim = self.claims.get(claim_id)
            if claim is None:
                raise LookupError("Pickup claim not found.")
            donation = self.donations[claim["donation_id"]]
            current = claim["status"]
            role, user_id = actor["role"], actor["id"]
            donor_owner = donation["donor_id"] == user_id
            recipient_owner = claim["recipient_id"] == user_id
            deadline = datetime.fromisoformat(donation["pickup_deadline"])
            expired = deadline <= self.now()
            if (
                new_status != ClaimStatus.CANCELLED.value
                and donation.get("safety_status") != SafetyStatus.ELIGIBLE.value
            ):
                raise ValueError("Safety review is required before this pickup can progress.")
            if expired:
                donation["status"] = DonationStatus.EXPIRED.value
                donation["safety_status"] = SafetyStatus.EXPIRED.value
                donation["safety_warnings"] = list(donation.get("safety_warnings", []))
                if "Pickup deadline has passed." not in donation["safety_warnings"]:
                    donation["safety_warnings"].append("Pickup deadline has passed.")
                donation["updated_at"] = self._iso(self.now())
                if new_status != ClaimStatus.CANCELLED.value:
                    raise ValueError("Pickup deadline has passed; this claim cannot progress.")

            if new_status == ClaimStatus.ACCEPTED.value:
                allowed = current == ClaimStatus.REQUESTED.value and (
                    role == "admin" or (role == "donor" and donor_owner)
                )
            elif new_status == ClaimStatus.READY_FOR_PICKUP.value:
                allowed = current == ClaimStatus.ACCEPTED.value and (
                    role == "admin" or (role == "donor" and donor_owner)
                )
            elif new_status == ClaimStatus.COMPLETED.value:
                allowed = current == ClaimStatus.READY_FOR_PICKUP.value and (
                    (role == "donor" and donor_owner)
                    or (role == "recipient" and recipient_owner)
                )
            elif new_status == ClaimStatus.CANCELLED.value:
                allowed = current in ACTIVE_CLAIM_STATUSES and (
                    role == "admin"
                    or (role == "donor" and donor_owner)
                    or (role == "recipient" and recipient_owner)
                )
            else:
                allowed = False
            if not allowed:
                raise PermissionError("This status transition is not allowed for your role or current status.")

            now = self._iso(self.now())
            claim["status"] = new_status
            claim["updated_at"] = now
            if new_status == ClaimStatus.COMPLETED.value:
                claim["completed_at"] = now
                donation["status"] = DonationStatus.COMPLETED.value
            elif new_status == ClaimStatus.CANCELLED.value:
                donation["status"] = (
                    DonationStatus.EXPIRED.value if expired else DonationStatus.AVAILABLE.value
                )
            else:
                donation["status"] = new_status
            donation["updated_at"] = now
            return dict(claim)

    def verify_recipient(self, recipient_id: str) -> dict:
        with self._lock:
            row = next((r for r in self.recipients if r["id"] == recipient_id), None)
            if not row:
                raise LookupError("Organization not found.")
            row["verification_status"] = "VERIFIED"
            return dict(row)

    def review_donation(
        self, donation_id: str, action: str, note: str, reviewer_id: str | None = None
    ) -> dict:
        with self._lock:
            donation = self.donations.get(donation_id)
            if not donation:
                raise LookupError("Donation not found.")
            if action == "withdraw":
                if donation["status"] in {
                    DonationStatus.COMPLETED.value,
                    DonationStatus.WITHDRAWN.value,
                }:
                    raise ValueError("Completed or already withdrawn donations cannot be withdrawn.")
                if any(
                    claim["donation_id"] == donation_id
                    and claim["status"] in ACTIVE_CLAIM_STATUSES
                    for claim in self.claims.values()
                ):
                    raise ValueError("Cancel the active pickup claim before withdrawing this donation.")
                donation["status"] = DonationStatus.WITHDRAWN.value
            elif action == "flag":
                donation["safety_status"] = SafetyStatus.FLAGGED.value
                donation["safety_warnings"] = list(donation.get("safety_warnings", []))
                donation["safety_warnings"].append(note or "Flagged for administrative safety review.")
            elif action == "resolve":
                deadline = datetime.fromisoformat(donation["pickup_deadline"])
                if deadline <= self.now():
                    raise ValueError("Expired donations cannot be cleared for pickup.")
                donation["safety_status"] = SafetyStatus.ELIGIBLE.value
                donation["safety_warnings"] = []
                donation["review_note"] = note or "Reviewed by a demo administrator."
            else:
                raise ValueError("Unsupported review action.")
            donation["updated_at"] = self._iso(self.now())
            return dict(donation)

    def profile_for_user(self, user_id: str) -> dict | None:
        if user_id in self.donors:
            return {"id": user_id, "role": "donor"}
        if any(row["id"] == user_id for row in self.recipients):
            return {"id": user_id, "role": "recipient"}
        if user_id == "demo-admin":
            return {"id": user_id, "role": "admin"}
        return None

    def admin_reviews(self) -> dict:
        claims = self.list_claims()
        donations = self.list_donations()
        return {
            "organizations": [
                row for row in self.list_recipients()
                if row["verification_status"] != "VERIFIED"
            ],
            "safety_reviews": [
                row for row in donations
                if row["safety_status"] in {
                    SafetyStatus.PENDING_REVIEW.value,
                    SafetyStatus.FLAGGED.value,
                    SafetyStatus.EXPIRED.value,
                }
            ],
            "active_claims": [row for row in claims if row["status"] in ACTIVE_CLAIM_STATUSES],
            "completed_donations": [
                row for row in donations if row["status"] == DonationStatus.COMPLETED.value
            ],
        }


class SupabaseStore:
    """Relational Supabase repository; privileged calls stay server-side."""

    mode = "supabase"

    def __init__(self, url: str, service_key: str, anon_key: str | None = None):
        try:
            from supabase import create_client
        except ImportError as exc:
            raise RuntimeError(
                "Supabase credentials are configured, but the 'supabase' package is not installed."
            ) from exc
        self.client = create_client(url, service_key)
        self.url = url.rstrip("/")
        self.anon_key = anon_key

    @staticmethod
    def _rows(table: str, query: Any) -> list[dict]:
        return query.execute().data or []

    def list_donations(self) -> list[dict]:
        rows = self._rows("donations", self.client.table("donations").select("*"))
        rows = self._with_donor_names(rows)
        return [self._expire(row) for row in rows]

    def get_donation(self, donation_id: str) -> dict | None:
        rows = self._rows(
            "donations",
            self.client.table("donations").select("*").eq("id", donation_id).limit(1),
        )
        if not rows:
            return None
        return self._expire(self._with_donor_names(rows)[0])

    def _with_donor_names(self, donations: list[dict]) -> list[dict]:
        donor_ids = list({row["donor_id"] for row in donations if row.get("donor_id")})
        if not donor_ids:
            return donations
        profiles = self._rows(
            "profiles",
            self.client.table("profiles")
            .select("id,display_name")
            .in_("id", donor_ids),
        )
        names = {profile["id"]: profile["display_name"] for profile in profiles}
        return [
            {**row, "donor_name": names.get(row.get("donor_id"), "FoodLoop donor")}
            for row in donations
        ]

    def _expire(self, donation: dict) -> dict:
        if donation["status"] == DonationStatus.AVAILABLE.value:
            deadline = datetime.fromisoformat(donation["pickup_deadline"].replace("Z", "+00:00"))
            if deadline <= datetime.now(timezone.utc):
                updates = {
                    "status": DonationStatus.EXPIRED.value,
                    "safety_status": SafetyStatus.EXPIRED.value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                warnings = list(donation.get("safety_warnings") or [])
                if "Pickup deadline has passed." not in warnings:
                    warnings.append("Pickup deadline has passed.")
                updates["safety_warnings"] = warnings
                self.client.table("donations").update(updates).eq("id", donation["id"]).execute()
                donation = {**donation, **updates}
        return donation

    def list_recipients(self) -> list[dict]:
        return self._rows("organizations", self.client.table("organizations").select("*"))

    def get_recipient(self, recipient_id: str) -> dict | None:
        rows = self._rows(
            "organizations",
            self.client.table("organizations").select("*").eq("id", recipient_id).limit(1),
        )
        return rows[0] if rows else None

    def get_donor_name(self, donor_id: str) -> str:
        rows = self._rows(
            "profiles",
            self.client.table("profiles").select("display_name").eq("id", donor_id).limit(1),
        )
        return rows[0]["display_name"] if rows else "FoodLoop donor"

    def list_claims(self) -> list[dict]:
        claims = self._rows("claims", self.client.table("claims").select("*"))
        for claim in claims:
            donation = self.get_donation(claim["donation_id"])
            if (
                donation
                and claim["status"] in ACTIVE_CLAIM_STATUSES
                and datetime.fromisoformat(donation["pickup_deadline"].replace("Z", "+00:00"))
                <= datetime.now(timezone.utc)
            ):
                updates = {
                    "status": DonationStatus.EXPIRED.value,
                    "safety_status": SafetyStatus.EXPIRED.value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                warnings = list(donation.get("safety_warnings") or [])
                if "Pickup deadline has passed." not in warnings:
                    warnings.append("Pickup deadline has passed.")
                updates["safety_warnings"] = warnings
                self.client.table("donations").update(updates).eq("id", donation["id"]).execute()
        return claims

    def get_claim(self, claim_id: str) -> dict | None:
        rows = self._rows(
            "claims",
            self.client.table("claims").select("*").eq("id", claim_id).limit(1),
        )
        return rows[0] if rows else None

    def create_donation(self, donation: dict, donor_id: str) -> dict:
        record = {
            **donation,
            "donor_id": donor_id,
            "status": DonationStatus.AVAILABLE.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        record = FoodDonation.model_validate(record).model_dump(mode="json")
        rows = self._rows("donations", self.client.table("donations").insert(record))
        return rows[0]

    def request_claim(self, donation_id: str, recipient_id: str, quantity: float) -> dict:
        try:
            result = self.client.rpc(
                "request_donation_claim",
                {
                    "p_donation_id": donation_id,
                    "p_recipient_id": recipient_id,
                    "p_requested_quantity": quantity,
                },
            ).execute()
        except Exception as exc:
            self._raise_domain_error(exc)
        if isinstance(result.data, dict) and result.data.get("error"):
            raise ValueError(result.data["error"])
        return result.data

    def transition_claim(self, claim_id: str, new_status: str, actor: dict) -> dict:
        try:
            result = self.client.rpc(
                "transition_donation_claim",
                {
                    "p_claim_id": claim_id,
                    "p_new_status": new_status,
                    "p_actor_id": actor.get("user_id", actor["id"]),
                    "p_actor_role": actor["role"],
                },
            ).execute()
        except Exception as exc:
            self._raise_domain_error(exc)
        if isinstance(result.data, dict) and result.data.get("error"):
            raise ValueError(result.data["error"])
        return result.data

    @staticmethod
    def _raise_domain_error(exc: Exception):
        message = str(getattr(exc, "message", "")) or "The requested database operation failed."
        lower = message.lower()
        if "not found" in lower:
            raise LookupError("Requested record was not found.") from exc
        if "verified" in lower:
            raise PermissionError("Only verified, available organizations may request donations.") from exc
        if "authorized" in lower:
            raise PermissionError("This status transition is not allowed for your role or current status.") from exc
        if "deadline" in lower:
            raise ValueError("The pickup deadline has passed.")
        if "quantity" in lower:
            raise ValueError("Requested quantity is outside the accepted range or pickup capacity.")
        if "available" in lower or "claim" in lower:
            raise ValueError("This donation is no longer available.")
        raise RuntimeError("Supabase database operation failed.") from exc

    def verify_recipient(self, recipient_id: str) -> dict:
        rows = self._rows(
            "organizations",
            self.client.table("organizations")
            .update({"verification_status": "VERIFIED"})
            .eq("id", recipient_id),
        )
        if not rows:
            raise LookupError("Organization not found.")
        return rows[0]

    def review_donation(
        self, donation_id: str, action: str, note: str, reviewer_id: str | None = None
    ) -> dict:
        if not reviewer_id:
            raise PermissionError("An authenticated administrator is required.")
        try:
            result = self.client.rpc(
                "review_food_donation",
                {
                    "p_donation_id": donation_id,
                    "p_action": action,
                    "p_note": note,
                    "p_reviewer_id": reviewer_id,
                },
            ).execute()
        except Exception as exc:
            self._raise_domain_error(exc)
        if isinstance(result.data, dict) and result.data.get("error"):
            message = result.data["error"]
            if "not found" in message.lower():
                raise LookupError(message)
            if "administrator" in message.lower() or "authorized" in message.lower():
                raise PermissionError(message)
            raise ValueError(message)
        return result.data

    def profile_for_user(self, user_id: str) -> dict | None:
        rows = self._rows(
            "profiles",
            self.client.table("profiles").select("id,role,organization_id").eq("id", user_id).limit(1),
        )
        return rows[0] if rows else None

    def admin_reviews(self) -> dict:
        claims = self.list_claims()
        donations = self.list_donations()
        return {
            "organizations": [
                row for row in self.list_recipients()
                if row["verification_status"] != "VERIFIED"
            ],
            "safety_reviews": [
                row for row in donations
                if row["safety_status"] in {
                    SafetyStatus.PENDING_REVIEW.value,
                    SafetyStatus.FLAGGED.value,
                    SafetyStatus.EXPIRED.value,
                }
            ],
            "active_claims": [row for row in claims if row["status"] in ACTIVE_CLAIM_STATUSES],
            "completed_donations": [
                row for row in donations if row["status"] == DonationStatus.COMPLETED.value
            ],
        }


def create_store():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if bool(url) != bool(key):
        raise RuntimeError("Set both SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, or neither for demo mode.")
    if url and key:
        return SupabaseStore(url, key, os.getenv("SUPABASE_ANON_KEY"))
    return DemoStore()
