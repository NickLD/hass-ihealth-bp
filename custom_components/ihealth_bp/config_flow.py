"""Config flow for iHealth Blood Pressure."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.selector import DateSelector, TimeSelector
from homeassistant.util import dt as dt_util

from .connection import MODEL, async_read_model
from .const import (
    CONF_DELETE_AFTER_IMPORT,
    CONF_EVENING_END,
    CONF_EVENING_START,
    CONF_MEASUREMENT_ROUTINE,
    CONF_MORNING_END,
    CONF_MORNING_START,
    CONF_REVIEW_MODE,
    CONF_ROUTINE_START,
    CONF_VARIANT,
    DOMAIN,
)
from .kn550bt.variants import Variant, variant_from_service_uuids
from .rejected import async_get_rejected
from .routine import windows_from_options

DEFAULT_OPTIONS = {
    CONF_DELETE_AFTER_IMPORT: True,
    CONF_REVIEW_MODE: False,
    CONF_MEASUREMENT_ROUTINE: True,
}


class IHealthBPConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iHealth Blood Pressure."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._variant: Variant | None = None
        self._discovered: dict[str, Variant] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return IHealthBPOptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        variant = variant_from_service_uuids(discovery_info.service_uuids, discovery_info.name)
        if variant is None:
            return self.async_abort(reason="not_supported")
        rejected = await async_get_rejected(self.hass)
        if discovery_info.address in rejected:
            return self.async_abort(reason="not_supported")
        # The cuff is only awake for ~10 s, so check the model now, not at confirm time.
        model = await async_read_model(discovery_info.device, variant)
        if model is not None and model != MODEL:
            await rejected.async_add(discovery_info.address)
            return self.async_abort(reason="not_supported")
        self._address, self._variant = discovery_info.address, variant
        self.context["title_placeholders"] = {"name": MODEL}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._address is not None and self._variant is not None
        if user_input is not None:
            return self._create_entry(self._address, self._variant)
        self._set_confirm_only()
        if self._variant.untested:
            return self.async_show_form(
                step_id="bluetooth_confirm_untested",
                description_placeholders={"name": MODEL, "variant": self._variant.value},
            )
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders={"name": MODEL}
        )

    # The same step with the untested-firmware note; HA submits to async_step_<step_id>.
    async_step_bluetooth_confirm_untested = async_step_bluetooth_confirm

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self._create_entry(address, self._discovered[address])

        current = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            variant = variant_from_service_uuids(info.service_uuids, info.name)
            if variant is not None and info.address not in current:
                self._discovered[info.address] = variant
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")
        choices = {
            address: f"{MODEL} ({address}){' - untested firmware' if v.untested else ''}"
            for address, v in self._discovered.items()
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(choices)}),
        )

    def _create_entry(self, address: str, variant: Variant) -> ConfigFlowResult:
        return self.async_create_entry(
            title=MODEL,
            data={CONF_ADDRESS: address, CONF_VARIANT: variant.value},
            options=dict(DEFAULT_OPTIONS),
        )


class IHealthBPOptionsFlow(OptionsFlow):
    """Options: what to do with readings once imported, then the measurement routine if on."""

    def __init__(self) -> None:
        self._base: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._base = user_input
            if user_input[CONF_MEASUREMENT_ROUTINE]:
                return await self.async_step_routine()
            # Keep the routine settings, so turning it back on restores them.
            return self.async_create_entry(data={**self.config_entry.options, **user_input})
        options = {**DEFAULT_OPTIONS, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DELETE_AFTER_IMPORT, default=options[CONF_DELETE_AFTER_IMPORT]
                    ): bool,
                    vol.Required(CONF_REVIEW_MODE, default=options[CONF_REVIEW_MODE]): bool,
                    vol.Required(
                        CONF_MEASUREMENT_ROUTINE, default=options[CONF_MEASUREMENT_ROUTINE]
                    ): bool,
                }
            ),
        )

    async def async_step_routine(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if windows_from_options(user_input).valid():
                return self.async_create_entry(data={**self._base, **user_input})
            errors["base"] = "invalid_windows"
        options = {**self.config_entry.options, **(user_input or {})}
        windows = windows_from_options(options)
        routine_start = options.get(CONF_ROUTINE_START) or dt_util.now().date().isoformat()
        return self.async_show_form(
            step_id="routine",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MORNING_START, default=windows.morning_start.isoformat()
                    ): TimeSelector(),
                    vol.Required(
                        CONF_MORNING_END, default=windows.morning_end.isoformat()
                    ): TimeSelector(),
                    vol.Required(
                        CONF_EVENING_START, default=windows.evening_start.isoformat()
                    ): TimeSelector(),
                    vol.Required(
                        CONF_EVENING_END, default=windows.evening_end.isoformat()
                    ): TimeSelector(),
                    vol.Required(CONF_ROUTINE_START, default=routine_start): DateSelector(),
                }
            ),
        )
