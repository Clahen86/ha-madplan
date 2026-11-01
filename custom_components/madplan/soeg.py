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
    "madolie": "rapsolie",
    "neutral olie": "rapsolie",
    "stegeolie": "rapsolie",
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
# Tilbud, der ikke bruges til aftensmad. De sorteres fra i madplanens prompt (ikke ved ekstra varer),
# så store kæder som føtex og Bilka ikke får et for langt svar fra AI'en.
IKKE_AFTENSMAD = re.compile(
    r"\bis\b|flødeis|juice|drik|sodavand|kildevand|danskvand|mineralvand|brus|saft|smoothie|shot|kakao|kaffe|espresso|cappuccino|"
    r"slik|chokolade|vingummi|lakrids|bolsjer|karamel|kiks|kage|cookie|muffin|croissant|wienerbrød|snack|"
    r"chips|popcorn|müsli|granola|cornflakes|marmelade|nutella|dessert|budding|konfekt|\bøl\b|pilsner|"
    r"\bipa\b|cider|\bvin\b|rosé|champagne|alkoholfri|likør|bitter|cola|energi|baby|grød|tyggegummi|"
    r"pastiller|vitamin|kosttilskud|\d+[.,]?\d*\s*%\s*vol|pålæg|leverpostej|spegepølse|rullepølse|skyr\b.*\b(?:vanilje|jordbær|hindbær|blåbær)",
    re.IGNORECASE,
)

# Basisvarer til aftensmad. AI'en får REMA's navne på dem, så den kan skrive et præcist navn.
# (Hele sortimentet er for langt: Gemini rammer sit loft for svarets længde.)
_BASISVARER = (
    "hakket oksekød", "hakket grisekød", "hakket kylling", "hakket kalv og flæsk", "kyllingebryst", "kyllingelår",
    "kyllingeinderfilet", "hel kylling", "kyllingefilet", "svinekoteletter", "flæskesteg", "medister", "pølser",
    "grillpølser", "bacon", "bacon i tern", "skinke", "skinkestrimler", "kalkun", "oksekød i tern", "oksefilet",
    "laks", "laksefilet", "torsk", "torskefilet", "sej", "rødspætte", "fiskefrikadeller", "fiskefilet", "rejer",
    "tun", "tun i vand", "makrel", "æg", "mælk", "letmælk", "sødmælk", "piskefløde", "madlavningsfløde",
    "creme fraiche", "smør", "margarine", "yoghurt naturel", "skyr", "revet ost", "mozzarella", "parmesan", "feta",
    "hytteost", "flødeost", "cheddar", "skiveost", "kartofler", "bagekartofler", "søde kartofler", "ris",
    "basmati ris", "jasmin ris", "spaghetti", "pasta", "penne", "makaroni", "lasagneplader", "nudler", "ægnudler",
    "couscous", "bulgur", "quinoa", "tortillas", "pitabrød", "burgerboller", "flutes", "rugbrød", "toastbrød",
    "naan", "løg", "rødløg", "hvidløg", "gulerødder", "broccoli", "blomkål", "spidskål", "hvidkål", "rødkål",
    "porrer", "squash", "aubergine", "peberfrugt", "rød peberfrugt", "agurk", "tomater", "cherrytomater", "salat",
    "icebergsalat", "spinat", "frossen spinat", "ærter", "majs", "grønne bønner", "champignon", "svampe", "selleri",
    "bladselleri", "pastinak", "rødbeder", "kål", "grønkål", "ingefær", "chili", "forårsløg", "persille",
    "basilikum", "koriander", "purløg", "dild", "hakkede tomater", "flåede tomater", "tomatpuré", "passata",
    "kokosmælk", "kidneybønner", "kikærter", "linser", "røde linser", "sorte bønner", "majs på dåse", "bouillon",
    "hønsebouillon", "grøntsagsbouillon", "sojasauce", "karry", "karrypasta", "paprika", "spidskommen", "oregano",
    "timian", "kanel", "salt", "peber", "olivenolie", "rapsolie", "olie", "eddike", "sukker", "mel", "hvedemel",
    "honning", "sennep", "ketchup", "mayonnaise", "pesto", "taco krydderi", "tacosauce", "salsa", "citron", "lime",
    "æbler", "bananer", "appelsiner", "pærer", "frosne grøntsager", "wokgrøntsager", "grøntsagsblanding",
    "frosne ærter", "pommes frites", "kartoffelbåde", "hummus", "oliven",
)
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
    "brød": 60, "boller": 60, "bolle": 60, "burgerboller": 60, "pitabrød": 70, "tortillas": 40, "wraps": 40,
    "pølser": 60, "pølse": 60, "kyllingebryst": 150, "kyllingebrystfilet": 150, "laksefilet": 125, "æg": 60,
    "spidskål": 800, "hvidkål": 1500, "rødkål": 1200, "blomkål": 700, "broccoli": 400, "kål": 1000,
    "salat": 300, "hjertesalat": 200, "selleri": 600, "fennikel": 300, "aubergine": 350, "majskolbe": 250,
    "filet": 110, "fileter": 110, "frikadelle": 50, "frikadeller": 50, "hakkebøf": 125, "hakkebøffer": 125,
    "kotelet": 150, "koteletter": 150, "schnitzel": 150, "kyllingelår": 200, "kyllingeinderfilet": 40,
    "kyllingeinderfileter": 40, "baguette": 300, "flutes": 150, "pitabrød": 70, "naanbrød": 130,
}


def stk_vaegt(navn: str) -> float | None:
    """Gram pr. stk ud fra ingrediensens navn - også sidste led i sammensatte ord ("rødspættefilet" -> filet)."""
    for o in reversed(_ord(navn)):
        if o in _STK_VAEGT:
            return _STK_VAEGT[o]
        if hoved := max((n for n in _STK_VAEGT if len(n) >= 4 and o.endswith(n)), key=len, default=None):
            return _STK_VAEGT[hoved]
    return None


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


def _noegle(navn: str) -> str:
    return " ".join((navn or "").lower().split())


# Undertitlen afslører en anden slags vare end navnet ("Citron" / "CHEASY, YOGHURT").
_ANDEN_TYPE = re.compile(
    r"\b(yoghurt|skyr|is|drik|juice|saft|sauce|dressing|chips|snack|suppe|dessert|kage|smoothie|marmelade|slik)\b",
    re.IGNORECASE,
)
# Varianter af samme vare - den almindelige udgave foretrækkes ("Hakkede tomater" frem for "M/CHILI").
_VARIANT = re.compile(r"\b[mu]/|lactofree|laktosefri|gluten|vegetar|vegansk|mini\b|bbq|chili|krydderi|hvidløg", re.I)


def _undertitel(strr: str) -> str:
    return strr.split(" / ", 1)[1] if " / " in strr else ""


def _passer_type(soegeord: str, v: dict) -> bool:
    """Falsk, hvis undertitlen siger en anden slags vare, end der søges efter."""
    m = _ANDEN_TYPE.search(_undertitel(v["str"]))
    return not m or m.group(1).lower() in (soegeord or "").lower() or m.group(1).lower() in v["navn"].lower()


def _variant(soegeord: str, v: dict) -> bool:
    m = _VARIANT.search(_undertitel(v["str"]))
    return bool(m) and m.group(0).lower() not in (soegeord or "").lower()


_navne_cache: dict[tuple, list[str]] = {}


def navneliste(katalog: dict[str, dict], dato: datetime.date) -> list[str]:
    """REMA's navne på basisvarerne, så AI'en kan vælge et præcist navn i stedet for at gætte."""
    noegle = (id(katalog), len(katalog), dato)
    if noegle not in _navne_cache:
        navne: dict[str, str] = {}
        for ord_ in _BASISVARER:
            if vid := find_vare(katalog, ord_, dato):
                navn = " ".join(katalog[vid]["navn"].split())
                navne.setdefault(_noegle(navn), navn)
        _navne_cache.clear()
        _navne_cache[noegle] = sorted(navne.values(), key=str.lower)
    return _navne_cache[noegle]


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

    Står søgeordet præcis som et varenavn (AI'en vælger fra navnelisten), bruges det direkte;
    ellers søges der på ordene.
    """
    noegle = _noegle(soegeord)
    praecis = [
        ((_pris_for(pris, v["str"], behov)[0], _variant(soegeord, v), _pris_for(pris, v["str"], behov)[1]), vid)
        for vid, v in katalog.items()
        if _noegle(v["navn"]) == noegle
        and not _stykvare(v["str"])
        and _passer_type(soegeord, v)
        and (pris := kilder.rema_pris(v, dato))
    ]
    if praecis:
        return min(praecis)[1]
    soegeord = _UDTRYK.get(" ".join((soegeord or "").lower().split()), soegeord)
    ord_ = [_SYNONYM.get(o, o) for o in _ord(soegeord) if o not in _FYLD] or _ord(soegeord)
    if not ord_:
        return None
    # Først alle ord, derefter kun hovedordet: det sidste ("friske champignon" -> "champignon"),
    # medmindre det er et bredt ord som "krydderi" - så det første.
    hoved = next((o for o in reversed(ord_) if o not in _GENERISK), None)
    for forsoeg in (ord_, [hoved]) if len(ord_) > 1 and hoved else (ord_,):
        kandidater: list[tuple[int, tuple[bool, bool, float], str]] = []
        for vid, v in katalog.items():
            if (kun_mad and IKKE_MAD.search(v["navn"])) or _stykvare(v["str"]) or not _passer_type(soegeord, v):
                continue
            s = _score(forsoeg, _ord(v["navn"]))
            if s is None or not (pris := kilder.rema_pris(v, dato)):
                continue
            enhed_forkert, koster = _pris_for(pris, v["str"], behov)
            kandidater.append((s, (enhed_forkert, _variant(soegeord, v), koster), vid))
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
