"""Opsætning af Madplan i brugerfladen."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import BUTIKKER, CONF_AI_ENTITY, CONF_BUTIK, CONF_INDKOBSLISTE, CONF_NOTIFY, DOMAIN, STANDARD_BUTIK

SKEMA = vol.Schema(
    {
        vol.Required(CONF_AI_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="ai_task")),
        vol.Required(CONF_BUTIK, default=STANDARD_BUTIK): selector.SelectSelector(
            selector.SelectSelectorConfig(options=list(BUTIKKER), translation_key=CONF_BUTIK)
        ),
        vol.Optional(CONF_INDKOBSLISTE): selector.EntitySelector(selector.EntitySelectorConfig(domain="todo")),
        vol.Optional(CONF_NOTIFY): selector.TextSelector(),
    }
)


class MadplanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Første opsætning."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Madplan", data={}, options=user_input)
        return self.async_show_form(step_id="user", data_schema=SKEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MadplanOptionsFlow()


class MadplanOptionsFlow(OptionsFlow):
    """Ret indstillinger bagefter."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=self.add_suggested_values_to_schema(SKEMA, self.config_entry.options)
        )
