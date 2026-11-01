"""Finder en vare i REMA's katalog ud fra et søgeord fra AI'en - uden AI.

AI'en får kun ugens tilbud. Til resten skriver den et søgeord ("hakkede tomater"),
og her vælges den billigste vare, der passer på navnet. Det sparer det meste af
AI-forbruget, fordi hele sortimentet ikke skal sendes med.
"""

from __future__ import annotations

import datetime
import math
import re

from . import kilder
from .const import IKKE_MAD

_ORD = re.compile(r"[a-zæøåéü]+")
_STR = re.compile(r"(?:(\d+)\s*X\s*)?(\d+(?:[.,]\d+)?)\s*(KG|GR|G|LTR|L|CL|ML|STK|PCS)\b", re.I)
_ENHED = {
    "kg": ("g", 1000),
    "gr": ("g", 1),
    "g": ("g", 1),
    "ltr": ("ml", 1000),
    "l": ("ml", 1000),
    "cl": ("ml", 10),
    "ml": ("ml", 1),
    "stk": ("stk", 1),
    "pcs": ("stk", 1),
}
# REMA forkorter i varenavnene, fx "Hk. oksekød", og kalder nogle varer noget andet.
_FORKORT = {"hk": "hakket", "fuldk": "fuldkorn", "kart": "kartoffel", "jomf": "jomfru", "eks": "ekstra"}
_SYNONYM = {
    "parmesan": "parmigiano",
    "parmesanost": "parmigiano",
    "feta": "fetaost",
    "svinekød": "grisekød",
    "svin": "gris",
    "grøntsager": "grøntsagsblanding",
    "wokgrøntsager": "grøntsagsblanding",
    "wraps": "tortillas",
    "wrap": "tortillas",
    "tortilla": "tortillas",
    "tortillawraps": "tortillas",
}
# Hele søgeord, AI'en typisk skriver, og hvad REMA kalder varen (ellers rammes fx "Tun i olie" for "olie").
_UDTRYK = {
    "mælk": "letmælk",
    "ris": "jasmin ris",
    "olie": "rapsolie",
    "mel": "hvedemel",
    "laks": "laksefilet",
    "torsk": "torskefileter",
    "sej": "mørksejfilet",
    "rejer": "rejer i lage",
    "kalkun": "kalkunbryst",
    "svampe": "champignon",
    "kål": "hvidkål",
    "salat": "hjertesalat",
    "icebergsalat": "iceberg salat",
    "peberfrugt": "rød peber",
    "peberfrugter": "rød peber",
    "rød peberfrugt": "rød peber",
    "gul peberfrugt": "gul/orange peber",
    "peber": "sort peber",
    "taco krydderi": "taco spice mix",
    "tacokrydderi": "taco spice mix",
    "salsa": "salsasauce",
    "toastbrød": "hvedetoast",
    "naan": "naanbrød",
    "vindruer": "druer",
    "frossen spinat": "hakket spinat",
    "frosne spinat": "hakket spinat",
    "appelsiner": "øko. appelsiner",
    "hakket kylling": "hk. kyllingekød",
    "hakket kyllingekød": "hk. kyllingekød",
    "hakket kalv og flæsk": "hk. gris & kalv",
    "hakket gris og kalv": "hk. gris & kalv",
    "hakket kalve- og flæskekød": "hk. gris & kalv",
    "oksekød i tern": "ungkvæg i tern",
    "svinekoteletter": "koteletter",
    "ægnudler": "nudler",
    "skyr": "skyr naturel",
    "snackgulerødder": "gulerødder",
    "gulerodsstave": "gulerødder",
}
# Ord, der er for brede til at søge på alene ("taco krydderi" må ikke blive til pebernødkrydderi).
_GENERISK = {"krydderi", "krydderier", "sauce", "mix", "blanding", "salat", "ost", "suppe", "fyld"}
_BOEJNING = ("e", "r", "er", "en", "n", "ne", "et", "s", "erne")
# Ord der beskriver mængde eller emballage og ikke står i varenavnene.
_FYLD = {"og", "med", "i", "til", "af", "på", "en", "et", "frisk", "friske", "dåse", "glas", "pakke", "pose", "stk"}
_FYLD |= {"frosne", "frossen", "frosset", "dybfrosne", "blandede"}
# Ord i varenavnet, der ikke gør varen til noget andet ("Øko. tomater", "Citron spanien kl. 1").
_NEUTRAL = (_FYLD - {"glas", "dåse"}) | {"m", "øko", "økologisk", "økologiske", "kl", "dansk", "danske", "spanien", "danmark", "holland"}


def stoerrelse(tekst: str) -> tuple[float, str] | None:
    """(mængde, 'g'|'ml'|'stk') fra REMA's størrelse, fx '400 GR. / ITALIEN' -> (400, 'g')."""
    m = _STR.search((tekst or "").split(" / ")[0])
    if not m:
        return None
    enhed, faktor = _ENHED[m.group(3).lower()]
    mgd = float(m.group(2).replace(",", ".")) * faktor * int(m.group(1) or 1)
    return (mgd, enhed) if mgd > 0 else None


def _ord(tekst: str) -> list[str]:
    return [_FORKORT.get(o, o) for o in _ORD.findall((tekst or "").lower())]


def _passer(t: str, w: str) -> int | None:
    """0 = samme ord (evt. bøjet), 1 = sidste led i et sammensat ord (piskefløde), None = nej."""
    if w == t or any(w == t + b or (len(w) >= 3 and t == w + b) for b in _BOEJNING):
        return 0
    if len(t) >= 3 and w.endswith(t):
        return 1
    return None


def _score(soeg: list[str], navn: list[str]) -> int | None:
    """Lavere er bedre: 2 pr. sammensat match (grødris for ris) og 1 pr. ekstra ord i navnet.

    None hvis et søgeord mangler.
    """
    brugt: set[int] = set()
    sammensat = 0
    for t in soeg:
        bedst = None
        for i, w in enumerate(navn):
            p = _passer(t, w)
            if p is not None and (bedst is None or p < bedst[1]):
                bedst = (i, p)
        if bedst is None:
            return None
        brugt.add(bedst[0])
        sammensat += bedst[1]
    ekstra = sum(1 for i, w in enumerate(navn) if i not in brugt and w not in _NEUTRAL)
    return 2 * sammensat + ekstra


# Ca. vægt pr. stk, når AI'en regner i stk, men varen sælges i gram (fx "4 stk løg" og en pose på 1 kg).
_STK_VAEGT = {
    "løg": 120, "rødløg": 100, "hvidløg": 50, "gulerod": 80, "gulerødder": 80, "kartoffel": 100, "kartofler": 100,
    "æble": 150, "æbler": 150, "pære": 150, "pærer": 150, "peberfrugt": 160, "peberfrugter": 160, "tomat": 100,
    "tomater": 100, "citron": 120, "citroner": 120, "lime": 70, "agurk": 350, "squash": 300, "porre": 250,
    "porrer": 250, "banan": 120, "bananer": 120, "avocado": 200, "avocadoer": 200, "appelsin": 200, "pastinak": 150,
}


def stk_vaegt(navn: str) -> float | None:
    """Gram pr. stk for almindelige grøntsager og frugt, ud fra ingrediensens navn."""
    return next((_STK_VAEGT[o] for o in reversed(_ord(navn)) if o in _STK_VAEGT), None)


def ligner(a: str, b: str) -> bool:
    """Om to varenavne har et fælles stykke ord på mindst 4 bogstaver ("Fiskefilet" ~ "mørksejfilet").
    Korte ord (ris, løg, æg) skal findes som hele ord."""
    b_ord = _ord(b)
    b_tekst = "".join(b_ord)
    for w in _ord(a):
        if len(w) >= 4 and any(w[i : i + 4] in b_tekst for i in range(len(w) - 3)):
            return True
        if len(w) < 4 and any(_passer(w, x) is not None or x.endswith(w) for x in b_ord):
            return True
    return False


def find_vare(
    katalog: dict[str, dict],
    soegeord: str,
    dato: datetime.date,
    behov: tuple[float, str] | None = None,
    kun_mad: bool = True,
) -> str | None:
    """Id på den billigste passende vare, eller None.

    behov = (mængde, enhed) for hele ugen: så vælges den vare, der dækker behovet billigst,
    i stedet for bare den billigste pakning.
    """
    soegeord = _UDTRYK.get(" ".join((soegeord or "").lower().split()), soegeord)
    ord_ = [_SYNONYM.get(o, o) for o in _ord(soegeord) if o not in _FYLD] or _ord(soegeord)
    if not ord_:
        return None
    # Først alle ord, derefter kun hovedordet: det sidste ("friske champignon" -> "champignon"),
    # medmindre det er et bredt ord som "krydderi" - så det første.
    hoved = next((o for o in reversed(ord_) if o not in _GENERISK), None)
    for forsoeg in (ord_, [hoved]) if len(ord_) > 1 and hoved else (ord_,):
        kandidater: list[tuple[int, tuple[bool, float], str]] = []
        for vid, v in katalog.items():
            if (kun_mad and IKKE_MAD.search(v["navn"])) or _stykvare(v["str"]):
                continue
            s = _score(forsoeg, _ord(v["navn"]))
            if s is None or not (pris := kilder.rema_pris(v, dato)):
                continue
            kandidater.append((s, _pris_for(pris, v["str"], behov), vid))
        if kandidater:
            bedste = min(k[0] for k in kandidater)
            return min((k for k in kandidater if k[0] == bedste), key=lambda k: k[1])[2]
    return None


def _stykvare(strr: str) -> bool:
    """Løsvægt pr. stk ("Løse kartofler, 0.07 KG, vej selv") - prisen gælder kun ét stk.
    Løsvægt pr. kg (fx hvidkål 1 KG vej selv) er fin."""
    if "VEJ SELV" not in strr.upper():
        return False
    s = stoerrelse(strr)
    return not s or s[0] < 250


def _pris_for(pris: float, strr: str, behov: tuple[float, str] | None) -> tuple[bool, float]:
    """(forkert enhed, pris) for at dække behovet - en vare i den rigtige enhed foretrækkes,
    så 1 stk søde kartofler ikke vinder over en pose kartofler, når der skal bruges gram."""
    if not behov or behov[0] <= 0:
        return False, pris
    if (s := stoerrelse(strr)) and s[1] == behov[1]:
        return False, math.ceil(behov[0] / s[0] - 0.15) * pris if behov[0] > s[0] else pris
    return True, pris
