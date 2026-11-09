"""Opsætning af Madplan i brugerfladen. Én opsætning pr. butik."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import kilder, rema_app
from .const import (
    BUTIKKER,
    CONF_AI_ENTITY,
    CONF_BUTIK,
    CONF_INDKOBSLISTE,
    CONF_NOTIFY,
    CONF_PROFIL,
    CONF_REMA_EMAIL,
    CONF_REMA_KODE,
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


def _forslag(options: dict[str, Any]) -> dict[str, Any]:
    """Gemte indstillinger som forslag. Ældre versioner gemte notify-tjenesterne som én tekst."""
    o = dict(options)
    if isinstance(o.get(CONF_NOTIFY), str):
        o[CONF_NOTIFY] = [t.strip() for t in o[CONF_NOTIFY].split(",") if t.strip()]
    return o


def _faelles_noegle(hass, undtagen: str | None = None) -> str:
    """Én Salling-nøgle til alle kæderne: den, der allerede er sat ind i en anden butik."""
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.entry_id != undtagen and (n := e.options.get(CONF_SALLING_NOEGLE)):
            return n
    return ""


def _butik_skema(butikker: list[dict], nu: str | None) -> vol.Schema:
    """Vælg butikken; listen er de nærmeste ved hjemmets placering i Home Assistant."""
    valg = [
        selector.SelectOptionDict(
            value=b["id"], label=f"{b['navn']}" + (f" ({b['km']:.1f} km)" if isinstance(b.get("km"), (int, float)) else "")
        )
        for b in butikker
    ]
    standard = nu if any(v["value"] == nu for v in valg) else valg[0]["value"]
    return vol.Schema(
        {
            vol.Required(CONF_SALLING_BUTIK, default=standard): selector.SelectSelector(
                selector.SelectSelectorConfig(options=valg, mode=selector.SelectSelectorMode.DROPDOWN)
            )
        }
    )


async def _hent_butikker(hass, noegle: str, butik: str) -> list[dict]:
    brand, _, radius = SALLING[butik]
    return await kilder.hent_salling_butikker(hass, noegle, brand, hass.config.latitude, hass.config.longitude, radius)


class MadplanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Første opsætning."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # Her tilføjes butikker til hovedprofilen; en anden profils butikker tilføjes fra kortet (Regler → Profiler).
        brugt = {e.data.get(CONF_BUTIK) for e in self._async_current_entries() if not e.data.get(CONF_PROFIL)}
        ledige = [b for b in BUTIKKER if b not in brugt]
        if not ledige:
            return self.async_abort(reason="alle_butikker")
        if user_input is not None:
            butik = user_input.pop(CONF_BUTIK)
            await self.async_set_unique_id(butik)
            self._abort_if_unique_id_configured()
            self._butik, self._valg = butik, user_input
            # Netto, føtex og Bilka bruger den Salling-nøgle, der allerede er sat ind: vælg kun butikken.
            if butik in SALLING and (noegle := _faelles_noegle(self.hass)):
                try:
                    self._butikker = await _hent_butikker(self.hass, noegle, butik)
                except Exception:  # noqa: BLE001 - nøglen kan sættes ind senere under Konfigurer
                    self._butikker = []
                if self._butikker:
                    self._valg = {**user_input, CONF_SALLING_NOEGLE: noegle}
                    return await self.async_step_butik()
            return self._opret(self._valg)
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
            skema = self.add_suggested_values_to_schema(skema, _forslag(forrige.options))
        return self.async_show_form(step_id="user", data_schema=skema)

    async def async_step_profil(self, data: dict[str, Any]) -> ConfigFlowResult:
        """En butik til en anden profil - oprettet fra kortet (madplan.gem_profil) med de andre butikkers AI og nøgler."""
        butik, profil = data[CONF_BUTIK], data[CONF_PROFIL]
        await self.async_set_unique_id(f"{butik}@{profil}")
        self._abort_if_unique_id_configured()
        reg = (self.hass.data.get(DOMAIN) or {}).get("profil_reg") or {}
        navn = ((reg.get("profiler") or {}).get(profil) or {}).get("navn") or profil
        return self.async_create_entry(
            title=f"Madplan {BUTIKKER[butik][0]} · {navn}", data={CONF_BUTIK: butik, CONF_PROFIL: profil}, options=data.get("options") or {}
        )

    def _opret(self, options: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(
            title=f"Madplan {BUTIKKER[self._butik][0]}", data={CONF_BUTIK: self._butik}, options=options
        )

    async def async_step_butik(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Din lokale butik i kæden - Salling-nøglen er allerede sat ind i en anden butik."""
        if user_input is not None:
            valgt = next((b for b in self._butikker if b["id"] == user_input[CONF_SALLING_BUTIK]), {})
            return self._opret(
                {**self._valg, CONF_SALLING_BUTIK: user_input[CONF_SALLING_BUTIK], CONF_SALLING_BUTIK_NAVN: valgt.get("navn") or ""}
            )
        return self.async_show_form(step_id="butik", data_schema=_butik_skema(self._butikker, None))

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
        if butik == "rema1000":
            felter[vol.Optional(CONF_REMA_EMAIL)] = selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
            )
            felter[vol.Optional(CONF_REMA_KODE)] = selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            )
        fejl: dict[str, str] = {}
        if user_input is not None and butik == "rema1000":
            email = (user_input.get(CONF_REMA_EMAIL) or "").strip()
            kode = user_input.get(CONF_REMA_KODE) or ""
            if email and not kode:
                fejl["base"] = "rema_login"
            elif email and (email, kode) != (self.config_entry.options.get(CONF_REMA_EMAIL), self.config_entry.options.get(CONF_REMA_KODE)):
                try:
                    await rema_app.async_test(self.hass, email, kode)
                except rema_app.RemaFejl as e:
                    fejl["base"] = "rema_login" if e.kode == "login" else "rema_forbindelse"
            if not email:
                user_input.pop(CONF_REMA_KODE, None)
            if fejl:
                return self.async_show_form(
                    step_id="init", data_schema=self.add_suggested_values_to_schema(vol.Schema(felter), user_input), errors=fejl
                )
        if user_input is not None:
            noegle = (user_input.pop(CONF_SALLING_NOEGLE, None) or "").strip()
            if not noegle or butik not in SALLING:
                return self.async_create_entry(data=user_input)
            try:
                self._butikker = await _hent_butikker(self.hass, noegle, butik)
            except Exception:  # noqa: BLE001 - forkert nøgle eller Salling nede
                fejl["base"] = "salling_fejl"
            else:
                if self._butikker:
                    self._data = {**user_input, CONF_SALLING_NOEGLE: noegle}
                    return await self.async_step_butik()
                fejl["base"] = "ingen_butikker"
        forslag = _forslag(user_input or self.config_entry.options)
        if butik in SALLING and not forslag.get(CONF_SALLING_NOEGLE):
            forslag[CONF_SALLING_NOEGLE] = _faelles_noegle(self.hass, self.config_entry.entry_id)
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
            self._del_noegle(self._data[CONF_SALLING_NOEGLE])
            return self.async_create_entry(
                data={**self._data, CONF_SALLING_BUTIK: user_input[CONF_SALLING_BUTIK], CONF_SALLING_BUTIK_NAVN: navn}
            )
        return self.async_show_form(
            step_id="butik", data_schema=_butik_skema(self._butikker, self.config_entry.options.get(CONF_SALLING_BUTIK))
        )

    def _del_noegle(self, noegle: str) -> None:
        """Én nøgle til alle kæderne: en ny nøgle her bruges også af de andre Salling-butikker."""
        for e in self.hass.config_entries.async_entries(DOMAIN):
            if e.entry_id != self.config_entry.entry_id and e.data.get(CONF_BUTIK) in SALLING \
                    and e.options.get(CONF_SALLING_NOEGLE) and e.options[CONF_SALLING_NOEGLE] != noegle:
                self.hass.config_entries.async_update_entry(e, options={**e.options, CONF_SALLING_NOEGLE: noegle})
