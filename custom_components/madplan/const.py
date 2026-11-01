"""Konstanter for Madplan."""

import re

DOMAIN = "madplan"

CONF_AI_ENTITY = "ai_entity"
CONF_INDKOBSLISTE = "indkobsliste"
CONF_NOTIFY = "notify_service"
CONF_BUTIK = "butik"

STANDARD_PERSONER = 4
# Familiens regler for madplanen - fælles for alle butikker.
STANDARD_REGLER = {
    "budget": None,  # kr pr. uge for hele familien
    "oeko": False,
    "allergier": [],
    "undgaa": [],
    "favoritter": [],
    "vegetar": 1,  # mindst så mange vegetarretter om ugen
    "fisk": 1,
    "max_tid": 40,  # minutter på hverdage
    "faste_dage": [],  # [{"dag": 5, "ret": "pizza"}], dag som indeks i DAGE
    "krav": "",
}

# Butik -> (navn, eTilbudsavis/Tjek dealer-id). Kun REMA har et åbent katalog med normalpriser;
# for de andre kæder bruges REMA's normalpriser som cirkapris for varer, der ikke er på tilbud.
BUTIKKER = {
    "rema1000": ("REMA 1000", "11deC"),
    "netto": ("Netto", "9ba51"),
    "foetex": ("føtex", "bdf5A"),
    "bilka": ("Bilka", "93f13"),
    "lidl": ("Lidl", "71c90"),
    "365discount": ("365discount", "DWZE1w"),
    "kvickly": ("Kvickly", "c1edq"),
    "superbrugsen": ("SuperBrugsen", "0b1e8"),
    "brugsen": ("Brugsen", "d311fg"),
    "meny": ("MENY", "267e1m"),
    "spar": ("SPAR", "88ddE"),
    "lovbjerg": ("Løvbjerg", "65caN"),
    "min_kobmand": ("Min Købmand", "603dfL"),
    "abc_lavpris": ("ABC Lavpris", "70d42L"),
}
STANDARD_BUTIK = "rema1000"

TJEK_CATALOGS_URL = "https://squid-api.tjek.com/v2/catalogs?dealer_ids={dealer}&country_id=DK&limit=100"
TJEK_URL = "https://squid-api.tjek.com/v2/offers?catalog_ids={catalog}&limit=100&offset={offset}"
TJEK_DEALER_OFFERS_URL = "https://squid-api.tjek.com/v2/offers?dealer_ids={dealer}&country_id=DK&limit=100&offset={offset}"
TJEK_DEALER_URL = "https://squid-api.tjek.com/v2/dealers/{dealer}"
REMA_URL = "https://api.digital.rema1000.dk/api/v3/products?per_page=100&page={side}"

SIGNAL_OPDATERET = "madplan_opdateret_{}"

DAGE = ["Søndag", "Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag"]
# Varer der aldrig indgår i aftensmad; holder AI-prompten kortere.
IKKE_MAD = re.compile(
    r"vask(?!ed)|skyl|shampoo|balsam|s[æa]be|tandpasta|tandb[øo]rste|deo|bleer|bind|toiletpapir|k[øo]kkenrulle|"
    r"servietter|batteri|led.?p[æa]re|\blys\b|\bposer?\b|folie|film|kattemad|hundemad|katte|hunde|snack|slik|"
    r"chokolade|vingummi|lakrids|chips|kiks|kage|\bis\b|sodavand|cola|energidrik|\b[øo]l\b|\bvin\b|spiritus|"
    r"vodka|\bgin\b|\brom\b|whisky|cider|kaffe|\bte\b|kapsler|tyggegummi|plaster|creme|lotion|barber|mascara|"
    r"neglelak|rengøring|klud|\bsvamp\b|(skure|stål|mirakel)svamp|ståluld|affaldsposer|fryseposer|gave|blomst",
    re.IGNORECASE,
)
# Aviser uden madvarer springes over (Bilka har fx legetøjs- og elektronikkataloger).
IKKE_MAD_AVIS = re.compile(r"non.?food|legetøj|beauty|vin|elektronik|prosonic|tekstil|bolig|have\b|jul\b|gaver", re.IGNORECASE)
HISTORIK_UGER = 8
UNDGAA_UGER = 4
KATALOG_MAX_ALDER = 6 * 86400
