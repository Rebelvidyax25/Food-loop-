from dataclasses import dataclass
from typing import Optional


@dataclass
class FoodListing:
	donor_name: str
	food_name: str
	quantity: str
	location: str
	pickup_deadline: str
	status: str = "Available"
	recipient_name: Optional[str] = None
