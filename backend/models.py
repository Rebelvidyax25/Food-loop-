from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class DonationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class SafetyStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ELIGIBLE = "ELIGIBLE"
    FLAGGED = "FLAGGED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ActorRole(str, Enum):
    DONOR = "donor"
    RECIPIENT = "recipient"
    ADMIN = "admin"


class Donor(BaseModel):
    id: str
    display_name: str
    role: Literal["donor"] = "donor"


class RecipientOrganization(BaseModel):
    id: str
    name: str
    verification_status: Literal["PENDING", "VERIFIED", "REJECTED"]
    preferred_categories: list[str]
    minimum_quantity: float = Field(gt=0)
    maximum_quantity: float = Field(gt=0)
    available: bool
    pickup_capacity: float = Field(ge=0)
    location: str
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    estimated_pickup_minutes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_quantity_range(self):
        if self.minimum_quantity > self.maximum_quantity:
            raise ValueError("Minimum quantity cannot exceed maximum quantity.")
        return self


class FoodDonation(BaseModel):
    id: str
    donor_id: str
    donor_name: str
    title: str
    category: str
    description: str
    quantity: float = Field(gt=0)
    unit: str
    prepared_at: datetime
    pickup_deadline: datetime
    donor_confirms_edible: bool
    storage_conditions: str
    allergens: list[str]
    allergen_info_known: bool
    location: str
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    minimum_quantity: Optional[float] = Field(default=None, gt=0)
    maximum_quantity: Optional[float] = Field(default=None, gt=0)
    status: DonationStatus
    safety_status: SafetyStatus
    safety_warnings: list[str]
    review_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("prepared_at", "pickup_deadline", "created_at", "updated_at")
    @classmethod
    def require_aware_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_deadline(self):
        if self.pickup_deadline <= self.prepared_at:
            raise ValueError("Pickup deadline must be after preparation time.")
        return self


class DonationClaim(BaseModel):
    id: str
    donation_id: str
    recipient_id: str
    requested_quantity: float = Field(gt=0)
    status: ClaimStatus
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class DonationCreate(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    category: str = Field(min_length=2, max_length=50)
    description: str = Field(default="", max_length=1000)
    quantity: float = Field(gt=0, le=100000)
    unit: str = Field(min_length=1, max_length=30)
    prepared_at: datetime
    pickup_deadline: datetime
    donor_confirms_edible: bool
    storage_conditions: str = Field(min_length=3, max_length=500)
    allergens: list[str] = Field(default_factory=list)
    allergen_info_known: bool
    location: str = Field(min_length=2, max_length=200)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    minimum_quantity: Optional[float] = Field(default=None, gt=0)
    maximum_quantity: Optional[float] = Field(default=None, gt=0)

    @field_validator("prepared_at", "pickup_deadline")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_donation(self):
        if self.pickup_deadline <= self.prepared_at:
            raise ValueError("Pickup deadline must be after preparation time.")
        if (
            self.minimum_quantity is not None
            and self.maximum_quantity is not None
            and self.minimum_quantity > self.maximum_quantity
        ):
            raise ValueError("Minimum quantity cannot exceed maximum quantity.")
        return self


class ClaimCreate(BaseModel):
    recipient_id: str = Field(min_length=1, max_length=100)
    requested_quantity: float = Field(gt=0, le=100000)


class ClaimStatusUpdate(BaseModel):
    status: ClaimStatus


class DonationReviewUpdate(BaseModel):
    action: str = Field(pattern="^(resolve|flag|withdraw)$")
    note: str = Field(default="", max_length=500)


class AuthLogin(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=256)


class MatchResult(BaseModel):
    recipient_id: str
    organization_name: str
    score: int
    component_scores: dict[str, Optional[int]]
    eligible: bool
    reasons: list[str]
