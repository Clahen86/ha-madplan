"""Opsætning af Madplan i brugerfladen. Én opsætning pr. butik."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import kilder
from .const import (
    BUTIKKER,
    CONF_AI_ENTITY,
    CONF_BUTIK,
    CONF_INDKOBSLISTE,
    CONF_NOTIFY,
    CONF_SALLING_BUTIK,
    CONF_SALLING_BUTIK_NAVN,
    CONF_SALLING_NOEGLE,
    DOMAIN,
    SALLING,
    STANDARD_BUTIK,
)

INDSTILLINGER = {
    vol.Required(CONF_AI_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="ai_task")),
    vol.Optional(CONF_INDKOBSLISTE): selector.EntitySelector(selector.EntitySelectorConfig(domain="todo")),
    # Én eller flere, fx notify.madplan_mail og begge telefoner.
    vol.Optional(CONF_NOTIFY): selector.TextSelector(selector.TextSelectorConfig(multiple=True)),
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
    """Ret indstillinger bagefter. Netto, føtex og Bilka kan få en Salling-nøgle til rigtige priser."""

    _data: dict[str, Any]
    _butikker: list[dict]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        butik = self.config_entry.data.get(CONF_BUTIK)
        felter = dict(INDSTILLINGER)
        if butik in SALLING:
            felter[vol.Optional(CONF_SALLING_NOEGLE)] = selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            )
        fejl: dict[str, str] = {}
        if user_input is not None:
            noegle = (user_input.pop(CONF_SALLING_NOEGLE, None) or "").strip()
            if not noegle or butik not in SALLING:
                return self.async_create_entry(data=user_input)
            brand, _, radius = SALLING[butik]
            try:
                self._butikker = await kilder.hent_salling_butikker(
                    self.hass, noegle, brand, self.hass.config.latitude, self.hass.config.longitude, radius
                )
            except Exception:  # noqa: BLE001 - forkert nøgle eller Salling nede
                fejl["base"] = "salling_fejl"
            else:
                if self._butikker:
                    self._data = {**user_input, CONF_SALLING_NOEGLE: noegle}
                    return await self.async_step_butik()
                fejl["base"] = "ingen_butikker"
        forslag = dict(user_input or self.config_entry.options)
        if isinstance(forslag.get(CONF_NOTIFY), str):  # gemt som én tekst før 1.1.0
            forslag[CONF_NOTIFY] = [t.strip() for t in forslag[CONF_NOTIFY].split(",") if t.strip()]
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(vol.Schema(felter), forslag),
            errors=fejl,
        )

    async def async_step_butik(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Vælg butikken; listen er de nærmeste ved hjemmets placering i Home Assistant."""
        if user_input is not None:
            valgt = next((b for b in self._butikker if b["id"] == user_input[CONF_SALLING_BUTIK]), {})
            navn = valgt.get("navn") or ""
            return self.async_create_entry(
                data={**self._data, CONF_SALLING_BUTIK: user_input[CONF_SALLING_BUTIK], CONF_SALLING_BUTIK_NAVN: navn}
            )
        nu = self.config_entry.options.get(CONF_SALLING_BUTIK)
        valg = [
            selector.SelectOptionDict(
                value=b["id"], label=f"{b['navn']}" + (f" ({b['km']:.1f} km)" if isinstance(b.get("km"), (int, float)) else "")
            )
            for b in self._butikker
        ]
        standard = nu if any(v["value"] == nu for v in valg) else valg[0]["value"]
        return self.async_show_form(
            step_id="butik",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SALLING_BUTIK, default=standard): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=valg, mode=selector.SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
        )
