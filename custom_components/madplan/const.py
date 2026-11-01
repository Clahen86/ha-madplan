"""Konstanter for Madplan."""

import re

DOMAIN = "madplan"

CONF_AI_ENTITY = "ai_entity"
CONF_INDKOBSLISTE = "indkobsliste"
CONF_NOTIFY = "notify_service"
CONF_BUTIK = "butik"

STANDARD_PERSONER = 4

# Butik -> eTilbudsavis (Tjek) dealer-id. REMA har også normalpriser via eget API.
BUTIKKER = {"rema1000": "11deC"}
STANDARD_BUTIK = "rema1000"

TJEK_URL = "https://squid-api.tjek.com/v2/offers?dealer_ids={dealer}&country_id=DK&limit=100&offset={offset}"
REMA_URL = "https://api.digital.rema1000.dk/api/v3/products?per_page=100&page={side}"

SIGNAL_OPDATERET = "madplan_opdateret_{}"

DAGE = ["Søndag", "Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag"]
# Varer der aldrig indgår i aftensmad; holder AI-prompten kortere.
IKKE_MAD = re.compile(
    r"vask|skyl|shampoo|balsam|s[æa]be|tandpasta|tandb[øo]rste|deo|bleer|bind|toiletpapir|k[øo]kkenrulle|"
    r"servietter|batteri|p[æa]re|lys\b|pose|folie|film|kattemad|hundemad|katte|hunde|snack|slik|chokolade|"
    r"vingummi|lakrids|chips|kiks|kage|is\b|sodavand|cola|energidrik|[øo]l\b|vin\b|spiritus|vodka|gin\b|"
    r"rom\b|whisky|cider|kaffe|te\b|kapsler|tyggegummi|plaster|creme|lotion|barber|mascara|neglelak|"
    r"rengøring|klud|svamp|affaldsposer|fryseposer|gave|blomst",
    re.IGNORECASE,
)
HISTORIK_UGER = 8
UNDGAA_UGER = 4
KATALOG_MAX_ALDER = 6 * 86400
