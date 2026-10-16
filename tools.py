from datetime import datetime


def create_food_listing(
    donor_name,
    food_name,
    quantity,
    location,
    pickup_deadline
):
    return {
        "donor_name": donor_name,
        "food_name": food_name,
        "quantity": quantity,
        "location": location,
        "pickup_deadline": pickup_deadline,
        "status": "Available",
        "created_at": datetime.now().isoformat()
    }


def get_available_food(listings):
    return [
        food for food in listings
        if food["status"] == "Available"
    ]


def claim_food(listings, food_index, recipient_name):
    if food_index < 0 or food_index >= len(listings):
        return "Invalid food listing."

    food = listings[food_index]

    if food["status"] != "Available":
        return "This food has already been claimed."

    food["status"] = "Claimed"
    food["recipient_name"] = recipient_name

    return "Food claimed successfully!"