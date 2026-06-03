"""Action registry constants."""

STANDARD_ACTIONS = {
    "search_listings": {
        "description": "Search property listings",
        "requires_confirmation": False,
        "external_api": True,
    },
    "get_listing_details": {
        "description": "Get full listing details",
        "requires_confirmation": False,
        "external_api": True,
    },
    "book_viewing": {
        "description": "Book property viewing",
        "requires_confirmation": True,
        "external_api": True,
    },
    "create_or_update_cv": {
        "description": "Create/update CV",
        "requires_confirmation": False,
        "external_api": False,
    },
    "schedule_lesson": {
        "description": "Schedule language lesson",
        "requires_confirmation": True,
        "external_api": False,
    },
    "send_email": {
        "description": "Send email notification",
        "requires_confirmation": True,
        "external_api": True,
    },
    "send_sms": {
        "description": "Send SMS notification",
        "requires_confirmation": True,
        "external_api": True,
    },
    "record_practice": {
        "description": "Record practice session (language tutor)",
        "requires_confirmation": False,
        "external_api": False,
    },
}
