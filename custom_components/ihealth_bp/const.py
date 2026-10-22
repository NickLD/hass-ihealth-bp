"""Constants for the iHealth Blood Pressure integration."""

DOMAIN = "ihealth_bp"

CONF_DELETE_AFTER_IMPORT = "delete_after_import"
CONF_REVIEW_MODE = "review_mode"

EVENT_MEASUREMENT = "ihealth_bp_measurement"
SERVICE_DELETE_READING = "delete_reading"
SERVICE_SET_READING_CONTEXT = "set_reading_context"
SERVICE_DELETE_SESSION = "delete_session"

# Seconds an advertisement must follow the previous session before we connect again.
POLL_INTERVAL_S = 30
CONF_VARIANT = "variant"

CONF_MORNING_START = "morning_start"
CONF_MORNING_END = "morning_end"
CONF_EVENING_START = "evening_start"
CONF_EVENING_END = "evening_end"
CONF_ROUTINE_START = "routine_start"

FLAGS: tuple[str, ...] = (
    "caffeine",
    "ate",
    "exertion",
    "after_shower",
    "poor_sleep",
    "alcohol",
    "stressed",
    "missed_meds",
    "sick",
)
