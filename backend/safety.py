from datetime import datetime, timezone

from .models import SafetyStatus


def _as_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def assess_safety(donation: dict, now: datetime | None = None) -> dict:
    """Assess information completeness; this is not a food-safety certification."""
    now = now or datetime.now(timezone.utc)
    warnings = []

    prepared_at = _as_datetime(donation.get("prepared_at"))
    deadline = _as_datetime(donation.get("pickup_deadline"))
    if not prepared_at:
        warnings.append("Preparation time is missing.")
    if not deadline:
        warnings.append("Pickup deadline is missing.")

    if prepared_at and deadline:
        if prepared_at >= deadline:
            warnings.append("Pickup deadline must be after preparation time.")
        if deadline <= now:
            return {
                "status": SafetyStatus.EXPIRED.value,
                "warnings": warnings + ["Pickup deadline has passed."],
            }
        if prepared_at > now:
            warnings.append("Preparation time is in the future and needs review.")

    if not donation.get("category"):
        warnings.append("Food category is missing.")
    if not donation.get("quantity") or donation.get("quantity", 0) <= 0:
        warnings.append("Quantity must be greater than zero.")
    if not donation.get("donor_confirms_edible", False):
        warnings.append("Donor has not confirmed the food is suitable for donation.")
    storage = (donation.get("storage_conditions") or "").strip()
    if len(storage) < 8:
        warnings.append("Storage information is incomplete and needs review.")
    elif any(
        term in storage.casefold()
        for term in ("room temperature", "left out", "unrefrigerated", "not sure", "unknown", "spoiled", "damaged")
    ):
        warnings.append("Storage details may need human safety review.")
    if not donation.get("allergen_info_known", False):
        warnings.append("Allergen information is unknown and needs human review.")

    status = SafetyStatus.PENDING_REVIEW.value if warnings else SafetyStatus.ELIGIBLE.value
    return {"status": status, "warnings": warnings}
