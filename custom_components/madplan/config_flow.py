"""Opsætning af Madplan i brugerfladen."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    BUTIKKER,
    CONF_AI_ENTITY,
    CONF_BUTIK,
    CONF_INDKOBSLISTE,
    CONF_PERSONER,
    DOMAIN,
    STANDARD_BUTIK,
    STANDARD_PERSONER,
)


def _skema(standard: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_AI_ENTITY, default=standard.get(CONF_AI_ENTITY)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="ai_task")
            ),
            vol.Required(CONF_INDKOBSLISTE, default=standard.get(CONF_INDKOBSLISTE)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="todo")
            ),
            vol.Required(CONF_PERSONER, default=standard.get(CONF_PERSONER, STANDARD_PERSONER)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=12, step=1, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_BUTIK, default=standard.get(CONF_BUTIK, STANDARD_BUTIK)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=list(BUTIKKER), translation_key=CONF_BUTIK)
            ),
        }
    )


class MadplanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Første opsætning."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            user_input[CONF_PERSONER] = int(user_input[CONF_PERSONER])
            return self.async_create_entry(title="Madplan", data={}, options=user_input)
        return self.async_show_form(step_id="user", data_schema=_skema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MadplanOptionsFlow()


class MadplanOptionsFlow(OptionsFlow):
    """Ret indstillinger bagefter."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            user_input[CONF_PERSONER] = int(user_input[CONF_PERSONER])
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="init", data_schema=_skema(dict(self.config_entry.options)))
