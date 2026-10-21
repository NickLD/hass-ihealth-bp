"""Config flow for iHealth Blood Pressure."""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class IHealthBPConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iHealth Blood Pressure."""

    VERSION = 1
