"""Opsætning af Madplan i brugerfladen. Én opsætning pr. butik."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import BUTIKKER, CONF_AI_ENTITY, CONF_BUTIK, CONF_INDKOBSLISTE, CONF_NOTIFY, DOMAIN, STANDARD_BUTIK

INDSTILLINGER = {
    vol.Required(CONF_AI_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="ai_task")),
    vol.Optional(CONF_INDKOBSLISTE): selector.EntitySelector(selector.EntitySelectorConfig(domain="todo")),
    vol.Optional(CONF_NOTIFY): selector.TextSelector(),
}


class MadplanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Første opsætning."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        brugt = {e.data.get(CONF_BUTIK) for e in self._async_current_entries()}
        ledige = [b for b in BUTIKKER if b not in brugt]
        if not ledige:
            return self.async_abort(reason="alle_butikker")
        if user_input is not None:
            butik = user_input.pop(CONF_BUTIK)
            await self.async_set_unique_id(butik)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Madplan {BUTIKKER[butik][0]}", data={CONF_BUTIK: butik}, options=user_input
            )
        # Forslag fra en eksisterende butik, så man ikke skal vælge AI-agent igen.
        forrige = next(iter(self._async_current_entries()), None)
        skema = vol.Schema(
            {
                vol.Required(CONF_BUTIK, default=STANDARD_BUTIK if STANDARD_BUTIK in ledige else ledige[0]): (
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[selector.SelectOptionDict(value=b, label=BUTIKKER[b][0]) for b in ledige],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                ),
                **INDSTILLINGER,
            }
        )
        if forrige:
            skema = self.add_suggested_values_to_schema(skema, forrige.options)
        return self.async_show_form(step_id="user", data_schema=skema)

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
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(vol.Schema(INDSTILLINGER), self.config_entry.options),
        )
