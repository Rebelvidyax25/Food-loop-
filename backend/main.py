import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .matching import rank_recipients
from .models import (
    ActorRole,
    AuthLogin,
    ClaimCreate,
    ClaimStatusUpdate,
    DonationCreate,
    DonationReviewUpdate,
)
from .safety import assess_safety
from .storage import DemoStore, create_store


logger = logging.getLogger("foodloop")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
load_dotenv()


def create_app(store=None) -> FastAPI:
    app = FastAPI(title="FoodLoop", version="1.0.0")
    app.state.store = store or create_store()
    origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:8000").split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Demo-Role", "X-Demo-User"],
    )

    @app.exception_handler(LookupError)
    async def not_found_handler(_request: Request, exc: LookupError):
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(PermissionError)
    async def permission_handler(_request: Request, exc: PermissionError):
        return JSONResponse(status_code=403, content={"error": str(exc)})

    @app.exception_handler(ValueError)
    async def conflict_handler(_request: Request, exc: ValueError):
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_request: Request, exc: Exception):
        logger.exception("Unhandled FoodLoop request error", exc_info=exc)
        return JSONResponse(status_code=500, content={"error": "The request could not be completed."})

    async def current_actor(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_demo_role: Optional[str] = Header(default=None),
        x_demo_user: Optional[str] = Header(default=None),
    ) -> dict:
        store = request.app.state.store
        if isinstance(store, DemoStore):
            role = (x_demo_role or "donor").lower()
            if role not in {item.value for item in ActorRole}:
                raise HTTPException(status_code=400, detail="Unknown demo role.")
            default_user = {
                "donor": "demo-canteen",
                "recipient": "org-neighborhood",
                "admin": "demo-admin",
            }[role]
            user_id = x_demo_user or default_user
            profile = store.profile_for_user(user_id)
            if not profile or profile["role"] != role:
                raise HTTPException(status_code=403, detail="Demo identity does not match the selected role.")
            return {"id": user_id, "user_id": user_id, "role": role, "demo": True}

        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="A valid Supabase access token is required.")
        token = authorization.split(" ", 1)[1].strip()
        if not token:
            raise HTTPException(status_code=401, detail="A valid Supabase access token is required.")
        try:
            user_response = store.client.auth.get_user(token)
            user = user_response.user
        except Exception as exc:
            logger.info("Supabase rejected an access token.")
            raise HTTPException(status_code=401, detail="Supabase access token is invalid or expired.") from exc
        if not user:
            raise HTTPException(status_code=401, detail="Supabase access token is invalid or expired.")
        profile = store.profile_for_user(user.id)
        if not profile:
            raise HTTPException(status_code=403, detail="No FoodLoop profile is associated with this account.")
        role = profile.get("role")
        if role not in {item.value for item in ActorRole}:
            raise HTTPException(status_code=403, detail="FoodLoop account has no authorized role.")
        return {
            "id": profile.get("organization_id") if role == "recipient" else user.id,
            "user_id": user.id,
            "role": role,
            "demo": False,
        }

    def require_role(actor: dict, *roles: str) -> None:
        if actor["role"] not in roles:
            raise HTTPException(status_code=403, detail="Your account is not authorized to perform this action.")

    @app.get("/")
    async def home():
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/status")
    async def status(request: Request):
        store = request.app.state.store
        return {
            "application": "FoodLoop",
            "mode": "demo" if isinstance(store, DemoStore) else "production",
            "storage": store.mode,
            "service": "available",
            "demo_notice": (
                "Synthetic demonstration data; changes are in-memory, are not shared across deployments, "
                "and may not survive a restart."
                if isinstance(store, DemoStore)
                else None
            ),
        }

    @app.post("/api/auth/login")
    async def auth_login(payload: AuthLogin, request: Request):
        store = request.app.state.store
        if isinstance(store, DemoStore):
            raise HTTPException(status_code=400, detail="Demo mode uses the clearly labelled role switcher.")
        if not store.anon_key:
            raise HTTPException(status_code=503, detail="Supabase sign-in is unavailable: SUPABASE_ANON_KEY is not configured.")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{store.url}/auth/v1/token?grant_type=password",
                    headers={"apikey": store.anon_key, "Content-Type": "application/json"},
                    json={"email": payload.email, "password": payload.password},
                )
        except httpx.HTTPError as exc:
            logger.exception("Supabase sign-in service request failed", exc_info=exc)
            raise HTTPException(status_code=503, detail="Supabase sign-in service is unavailable.") from exc
        if response.status_code >= 400:
            raise HTTPException(status_code=401, detail="Email or password is incorrect.")
        data = response.json()
        if not data.get("access_token"):
            logger.error("Supabase sign-in response did not include an access token.")
            raise HTTPException(status_code=502, detail="Supabase sign-in returned an invalid response.")
        try:
            user_response = store.client.auth.get_user(data["access_token"])
            user = user_response.user
        except Exception as exc:
            logger.exception("Could not verify the signed-in Supabase identity", exc_info=exc)
            raise HTTPException(status_code=502, detail="Could not verify the Supabase sign-in response.") from exc
        profile = store.profile_for_user(user.id) if user else None
        if not profile:
            raise HTTPException(status_code=403, detail="No FoodLoop profile is associated with this account.")
        role = profile.get("role")
        if role not in {item.value for item in ActorRole}:
            raise HTTPException(status_code=403, detail="FoodLoop account has no authorized role.")
        return {
            "access_token": data["access_token"],
            "expires_in": data.get("expires_in"),
            "role": role,
            "identity": profile.get("organization_id") if role == "recipient" else user.id,
        }

    @app.get("/api/auth/me")
    async def auth_me(actor: dict = Depends(current_actor)):
        return {"role": actor["role"], "identity": actor["id"]}

    @app.get("/api/donations")
    async def list_donations(
        request: Request,
        search: str = "",
        category: str = "",
        location: str = "",
        status_filter: str = Query(default="", alias="status"),
        minimum_quantity: Optional[float] = Query(default=None, ge=0),
        before_deadline: Optional[datetime] = None,
        include_history: bool = False,
    ):
        if before_deadline and (
            before_deadline.tzinfo is None
            or before_deadline.utcoffset() is None
        ):
            raise HTTPException(status_code=422, detail="before_deadline must include a timezone.")
        rows = request.app.state.store.list_donations()
        query = search.strip().casefold()
        category_filter = category.strip().casefold()
        location_filter = location.strip().casefold()
        results = []
        for row in rows:
            if not include_history and row["status"] in {"WITHDRAWN", "COMPLETED"}:
                continue
            if query and query not in " ".join(
                str(row.get(key, "")) for key in ("title", "description", "category", "location")
            ).casefold():
                continue
            if category_filter and category_filter not in row["category"].casefold():
                continue
            if location_filter and location_filter not in row["location"].casefold():
                continue
            if status_filter and row["status"] != status_filter.upper():
                continue
            if minimum_quantity is not None and row["quantity"] < minimum_quantity:
                continue
            if before_deadline and datetime.fromisoformat(row["pickup_deadline"]) > before_deadline:
                continue
            results.append(row)
        return sorted(results, key=lambda row: (row["status"] != "AVAILABLE", row["pickup_deadline"]))

    @app.post("/api/donations", status_code=201)
    async def create_donation(
        payload: DonationCreate,
        request: Request,
        actor: dict = Depends(current_actor),
    ):
        require_role(actor, "donor")
        store = request.app.state.store
        now = request.app.state.store.now() if isinstance(request.app.state.store, DemoStore) else datetime.now(timezone.utc)
        if not payload.donor_confirms_edible:
            raise HTTPException(status_code=422, detail="Food must be confirmed edible and suitable for donation.")
        if payload.pickup_deadline <= now:
            raise HTTPException(status_code=422, detail="Pickup deadline must be in the future.")
        donation = payload.model_dump(mode="json")
        safety = assess_safety(donation, now=now)
        donation["safety_status"] = safety["status"]
        donation["safety_warnings"] = safety["warnings"]
        return store.create_donation(donation, donor_id=actor["user_id"])

    @app.get("/api/donations/{donation_id}")
    async def donation_detail(donation_id: str, request: Request):
        donation = request.app.state.store.get_donation(donation_id)
        if donation is None:
            raise LookupError("Donation not found.")
        donation["claims"] = [
            claim for claim in request.app.state.store.list_claims()
            if claim["donation_id"] == donation_id
        ]
        return donation

    @app.get("/api/donations/{donation_id}/matches")
    async def donation_matches(donation_id: str, request: Request):
        store = request.app.state.store
        donation = store.get_donation(donation_id)
        if donation is None:
            raise LookupError("Donation not found.")
        if donation["status"] != "AVAILABLE" or donation["safety_status"] != "ELIGIBLE":
            raise ValueError("Ranked matches are available only for safety-cleared available donations.")
        now = store.now()
        return {
            "donation_id": donation_id,
            "weights": {"distance": 35, "urgency": 25, "quantity": 25, "availability": 15},
            "matches": rank_recipients(donation, store.list_recipients(), now=now),
        }

    @app.post("/api/donations/{donation_id}/claims", status_code=201)
    async def request_claim(
        donation_id: str,
        payload: ClaimCreate,
        request: Request,
        actor: dict = Depends(current_actor),
    ):
        require_role(actor, "recipient")
        if actor["id"] != payload.recipient_id:
            raise HTTPException(status_code=403, detail="You may only request food for your own organization.")
        return request.app.state.store.request_claim(
            donation_id, payload.recipient_id, payload.requested_quantity
        )

    @app.get("/api/claims")
    async def list_claims(request: Request, actor: dict = Depends(current_actor)):
        store = request.app.state.store
        claims = store.list_claims()
        if actor["role"] == "donor":
            donation_by_id = {item["id"]: item for item in store.list_donations()}
            claims = [
                claim for claim in claims
                if donation_by_id.get(claim["donation_id"], {}).get("donor_id") == actor["user_id"]
            ]
        elif actor["role"] == "recipient":
            claims = [claim for claim in claims if claim["recipient_id"] == actor["id"]]
        enriched = []
        donations = {item["id"]: item for item in store.list_donations()}
        recipients = {item["id"]: item for item in store.list_recipients()}
        for claim in claims:
            donation = donations.get(claim["donation_id"], {})
            recipient = recipients.get(claim["recipient_id"], {})
            enriched.append(
                {
                    **claim,
                    "donation_title": donation.get("title", "Donation"),
                    "donor_name": donation.get("donor_name") or store.get_donor_name(donation.get("donor_id", "")),
                    "pickup_deadline": donation.get("pickup_deadline"),
                    "location": donation.get("location"),
                    "unit": donation.get("unit"),
                    "organization_name": recipient.get("name", "Recipient organization"),
                    "donation_status": donation.get("status"),
                }
            )
        return enriched

    @app.patch("/api/claims/{claim_id}/status")
    async def update_claim_status(
        claim_id: str,
        payload: ClaimStatusUpdate,
        request: Request,
        actor: dict = Depends(current_actor),
    ):
        return request.app.state.store.transition_claim(
            claim_id, payload.status.value, actor
        )

    @app.get("/api/impact")
    async def impact(request: Request):
        store = request.app.state.store
        donations = store.list_donations()
        claims = store.list_claims()
        completed = [
            item for item in donations if item["status"] == "COMPLETED"
        ]
        portions = sum(
            item["quantity"]
            for item in completed
            if item["unit"].strip().casefold() in {"portion", "portions"}
        )
        return {
            "completed_donations": len(completed),
            "portions_donated": portions,
            "active_available_listings": sum(
                item["status"] == "AVAILABLE" and item["safety_status"] == "ELIGIBLE"
                for item in donations
            ),
            "active_pickup_claims": sum(item["status"] in {"REQUESTED", "ACCEPTED", "READY_FOR_PICKUP"} for item in claims),
            "estimated_food_waste_avoided_kg": round(portions * 0.4, 2),
            "assumption": "Estimated at 0.4 kg per donated portion; estimate only, not a measured reduction.",
            "recent_completed": sorted(completed, key=lambda item: item["updated_at"], reverse=True)[:5],
            "demo_data": isinstance(store, DemoStore),
            "activity_notice": (
                "Includes synthetic seeded demonstration records."
                if isinstance(store, DemoStore)
                else "Calculated from records in the configured Supabase project."
            ),
        }

    @app.get("/api/admin/reviews")
    async def admin_reviews(request: Request, actor: dict = Depends(current_actor)):
        require_role(actor, "admin")
        return request.app.state.store.admin_reviews()

    @app.patch("/api/admin/organizations/{organization_id}/verify")
    async def verify_organization(
        organization_id: str,
        request: Request,
        actor: dict = Depends(current_actor),
    ):
        require_role(actor, "admin")
        return request.app.state.store.verify_recipient(organization_id)

    @app.patch("/api/admin/donations/{donation_id}/review")
    async def review_donation(
        donation_id: str,
        payload: DonationReviewUpdate,
        request: Request,
        actor: dict = Depends(current_actor),
    ):
        require_role(actor, "admin")
        return request.app.state.store.review_donation(
            donation_id, payload.action, payload.note, reviewer_id=actor["user_id"]
        )

    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    return app


app = create_app()
