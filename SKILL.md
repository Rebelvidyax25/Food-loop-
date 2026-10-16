# FoodLoop — Food Donation Coordination

Build a Python command-line prototype that connects food donors with authorized community organizations and helps reduce avoidable food waste.

## Requirements

- Use an object-oriented data model for donors, recipient organizations, and food donations.
- Keep prototype data in memory.
- Let donors create surplus-food listings with accurate quantities, food suitability and safe-handling details, and pickup deadlines.
- Let users view available donations, claim food for pickup, and track donation status.
- Record donor and recipient information.
- Accept only suitable, safely handled edible food. Validate quantities and deadlines.
- Require recipients to be authorized organizations.
- Prevent a donation from being claimed more than once.
- Ensure pickups happen within safe time limits; reject pickup after the deadline.
- Provide clear command-line prompts, input validation, and status feedback.

## Suggested donation lifecycle

`AVAILABLE` → `CLAIMED` → `PICKED_UP`

Mark a donation unavailable to other recipients as soon as it is claimed. Handle expiration explicitly if supported.

## Future improvements

Keep future extensions in mind: a web interface using HTML, CSS, and JavaScript; Firebase persistence; donor and recipient authentication; location-based food discovery; pickup notifications; and an impact dashboard. These are not required for the in-memory prototype.
