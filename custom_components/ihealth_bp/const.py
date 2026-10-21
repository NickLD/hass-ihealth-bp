"""Constants for the iHealth Blood Pressure integration."""

DOMAIN = "ihealth_bp"

CONF_DELETE_AFTER_IMPORT = "delete_after_import"
CONF_REVIEW_MODE = "review_mode"

EVENT_MEASUREMENT = "ihealth_bp_measurement"
SERVICE_DELETE_READING = "delete_reading"

# Seconds an advertisement must follow the previous session before we connect again.
POLL_INTERVAL_S = 30
CONF_VARIANT = "variant"
