"""Allergigrupper: "gluten" -> pasta, tortilla, brød … så både AI'en og tjekket forstår dem.

Dækker de 14 EU-allergener plus de mest almindelige andre (natskygge, løg, citrus, kød …).
Står allergien ikke her, bruges ordet som det er (fx "kiwi").
"""

from __future__ import annotations

import re

# navn: (varer der rammer, undtagelser der ikke rammer, "fri"-ord der gør varen ok)
# Et ord med "=" foran skal stå som helt ord (fx "=and" må ikke ramme "mandel").
GRUPPER: dict[str, tuple[list[str], list[str], list[str]]] = {
    "gluten": (
        ["hvede", "spelt", "rug", "byg", "havre", "mel", "pasta", "spaghetti", "penne", "fusilli", "makaroni",
         "lasagne", "tagliatelle", "pappardelle", "tortellini", "ravioli", "gnocchi", "nudler", "udon", "ramen",
         "tortilla", "wrap", "pita", "naan", "brød", "bolle", "flute", "baguette", "ciabatta", "focaccia", "rasp",
         "panko", "paneret", "couscous", "bulgur", "seitan", "sojasauce", "hoisin", "teriyaki", "=øl", "butterdej",
         "tærtedej", "pizzadej", "pizzabund", "grissini", "kiks", "pandekage", "croutons", "orzo"],
        ["boghvede", "majsmel", "rismel", "kartoffelmel", "mandelmel", "kikærtemel", "kokosmel", "melon", "karamel",
         "risnudler", "glasnudler", "majstortilla", "majs tortilla", "tamari", "risnudel", "melis", "tomatpasta",
         "karrypasta", "currypasta", "chilipasta", "sesampasta", "misopasta", "hvidløgspasta", "ingefærpasta",
         "raspet", "grapetomat"],
        ["glutenfri", "uden gluten"],
    ),
    "mælk": (
        ["mælk", "fløde", "smør", "ost", "parmesan", "mozzarella", "feta", "cheddar", "mascarpone", "ricotta",
         "halloumi", "brie", "gouda", "burrata", "pecorino", "grana padano", "yoghurt", "creme fraiche",
         "crème fraîche", "cremefraiche", "skyr", "kvark", "ymer", "valle", "bechamel", "ghee", "smørdej"],
        ["kokosmælk", "havremælk", "mandelmælk", "sojamælk", "rismælk", "kokosfløde", "havrefløde", "sojafløde",
         "jordnøddesmør", "peanutbutter", "nøddesmør", "mandelsmør", "smørbønne", "plantesmør", "kokosyoghurt",
         "sojayoghurt", "havreyoghurt", "rost", "frost", "kost"],
        ["laktosefri", "mælkefri", "vegansk", "plantebaseret", "uden laktose", "uden mælk", "lactofree"],
    ),
    "æg": (
        ["æg", "mayonnaise", "mayo", "remoulade", "aioli", "bearnaise", "hollandaise", "marengs"],
        ["vegansk mayo", "ægte"],
        ["ægfri", "uden æg", "vegansk"],
    ),
    "fisk": (
        ["fisk", "laks", "torsk", "=tun", "tunfisk", "makrel", "sild", "rødspætte", "=sej", "kuller", "ansjos",
         "sardin", "ørred", "pangasius", "hellefisk", "rogn", "kaviar"],
        [],
        [],
    ),
    "skaldyr": (
        ["reje", "krabbe", "hummer", "langust", "krebs", "scampi"],
        [],
        [],
    ),
    "bløddyr": (
        ["musling", "østers", "blæksprutte", "calamari", "snegl"],
        ["østershat", "østerssvamp"],
        [],
    ),
    "nødder": (
        ["nød", "mandel", "mandl", "hasselnød", "valnød", "cashew", "pistacie", "pekan", "paranød", "macadamia",
         "pinje", "pesto", "marcipan", "nougat", "nutella", "praliné"],
        ["muskatnød", "kokosnød", "jordnød"],
        ["nøddefri", "uden nødder"],
    ),
    "jordnødder": (
        ["jordnød", "peanut", "satay"],
        [],
        [],
    ),
    "sesam": (
        ["sesam", "tahin", "hummus", "halva"],
        [],
        [],
    ),
    "soja": (
        ["soja", "tofu", "edamame", "miso", "tempeh", "tamari"],
        [],
        ["sojafri", "uden soja"],
    ),
    "selleri": (
        ["selleri"],
        [],
        [],
    ),
    "sennep": (
        ["sennep", "dijon"],
        [],
        [],
    ),
    "lupin": (
        ["lupin"],
        [],
        [],
    ),
    "sulfit": (
        ["sulfit", "rødvin", "hvidvin", "=vin", "portvin", "rosin", "tørrede abrikoser", "vineddike"],
        [],
        [],
    ),
    "bælgfrugter": (
        ["ært", "linse", "kikært", "bønne", "edamame", "hummus", "falafel", "soja", "tofu", "jordnød"],
        ["kaffebønne"],
        [],
    ),
    "natskygge": (
        ["tomat", "kartof", "peberfrugt", "aubergine", "chili", "paprika", "jalapeño", "jalapeno", "cayenne",
         "ketchup", "pommes", "harissa", "sriracha"],
        ["sød kartof", "søde kartof", "sødkartof", "sødekartof"],
        [],
    ),
    "løg": (
        ["løg", "porre", "skalotte"],
        [],
        [],
    ),
    "citrus": (
        ["citron", "lime", "appelsin", "grape", "mandarin", "clementin", "yuzu", "pomelo"],
        ["citrongræs", "citronmelisse", "grapetomat"],
        [],
    ),
    "stenfrugt": (
        ["kirsebær", "blomme", "fersken", "abrikos", "nektarin", "sveske"],
        ["æggeblomme"],
        [],
    ),
    "æble": (
        ["æble"],
        [],
        [],
    ),
    "pære": (
        ["pære"],
        [],
        [],
    ),
    "svinekød": (
        ["svin", "flæsk", "bacon", "skinke", "pancetta", "chorizo", "pølse", "salami", "medister", "ribben",
         "hamburgerryg", "gris"],
        ["kalkunbacon", "kyllingeskinke", "kalkunskinke", "kyllingepølse", "kalkunpølse", "vegetarpølse",
         "grissini"],
        [],
    ),
    "rødt kød": (
        ["okse", "kalv", "=lam", "lammekød", "lammekølle", "bøf", "hjort", "vildt", "svin", "flæsk", "bacon",
         "skinke", "pancetta", "chorizo", "pølse", "salami", "medister", "ribben", "gris"],
        ["kalkunbacon", "kyllingeskinke", "kalkunskinke", "kyllingepølse", "kalkunpølse", "vegetarpølse",
         "grissini"],
        [],
    ),
    "fjerkræ": (
        ["kylling", "kalkun", "=and", "andebryst", "andelår", "andesteg", "andekød", "gås", "perlehøne"],
        [],
        [],
    ),
    "majs": (
        ["majs", "polenta", "popcorn", "nachos", "maizena"],
        [],
        [],
    ),
    "svampe": (
        ["svamp", "champignon", "portobello", "kantarel", "shiitake", "østershat", "karl johan", "trøffel"],
        [],
        [],
    ),
    "kokos": (
        ["kokos"],
        [],
        [],
    ),
    "koriander": (
        ["koriander"],
        [],
        [],
    ),
}

# Andre måder at skrive det samme på.
SYNONYMER: dict[str, str] = {
    "cøliaki": "gluten", "glutenintolerans": "gluten", "glutenintolerance": "gluten", "hvede": "gluten",
    "hvedeallergi": "gluten",
    "laktose": "mælk", "laktoseintolerans": "mælk", "laktoseintolerance": "mælk", "mælkeprotein": "mælk",
    "mejeri": "mælk", "mejeriprodukter": "mælk", "mælkeprodukter": "mælk", "komælk": "mælk", "mælke": "mælk",
    "æg": "æg", "ægge": "æg", "hønseæg": "æg",
    "fisk": "fisk", "fiske": "fisk",
    "skaldyr": "skaldyr", "skaldyrs": "skaldyr", "krebsdyr": "skaldyr", "rejer": "skaldyr",
    "bløddyr": "bløddyr", "muslinger": "bløddyr",
    "nød": "nødder", "nødde": "nødder", "nødder": "nødder", "trænødder": "nødder", "trænød": "nødder",
    "jordnød": "jordnødder", "jordnødde": "jordnødder", "peanuts": "jordnødder", "peanut": "jordnødder",
    "sesamfrø": "sesam",
    "sojabønner": "soja",
    "sennepsfrø": "sennep", "senneps": "sennep",
    "svovldioxid": "sulfit", "sulfitter": "sulfit",
    "bælgplanter": "bælgfrugter", "bælgfrugt": "bælgfrugter",
    "natskyggefamilien": "natskygge", "natskyggeplanter": "natskygge",
    "hvidløg": "løg", "allium": "løg",
    "citrusfrugter": "citrus", "citrusfrugt": "citrus",
    "stenfrugter": "stenfrugt", "birk": "stenfrugt", "birkepollen": "stenfrugt",
    "æbler": "æble", "pærer": "pære",
    "svin": "svinekød", "gris": "svinekød", "grisekød": "svinekød",
    "alfa-gal": "rødt kød", "alfagal": "rødt kød", "alpha-gal": "rødt kød", "rødt kød": "rødt kød",
    "kød": "rødt kød", "oksekød": "rødt kød",
    "kylling": "fjerkræ", "fjerkræ": "fjerkræ",
    "svampe": "svampe", "svamp": "svampe",
}

_STOEJ = re.compile(r"\b(?:allergi(?:sk)?|intoleran[st]|overfor|over for|mod|for)\b", re.I)


def gruppe(allergi: str) -> str | None:
    """'Glutenallergi' / 'cøliaki' / 'Allergisk over for nødder' -> gruppens navn, ellers None."""
    a = _STOEJ.sub(" ", str(allergi or "").lower())
    a = re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", a)).strip(" -")
    for hale in ("allergi", "intolerans", "intolerance", "intolerant", "frit", "fri"):
        if a.endswith(hale) and len(a) > len(hale):
            a = a[: -len(hale)].strip()
    if a in GRUPPER:
        return a
    return SYNONYMER.get(a)


def opdel(allergier: list[str]) -> list[tuple[str, str | None]]:
    """['Gluten- og laktoseallergi', 'kiwi'] -> [('gluten', 'gluten'), ('laktose', 'mælk'), ('kiwi', None)]."""
    ud: list[tuple[str, str | None]] = []
    for a in allergier or []:
        a = str(a or "").strip()
        if not a:
            continue
        g = gruppe(a)
        if g or not re.search(r",|/|\bog\b|&", a):
            ud.append((a, g))
            continue
        dele = [d.strip(" -") for d in re.split(r",|/|\bog\b|&", a) if d.strip(" -")]
        hale = re.search(r"(allergi\w*|intoleran\w*)$", dele[-1].replace(" ", "")) if dele else None
        for d in dele:
            ud.append((d, gruppe(d) or (gruppe(d + hale.group(1)) if hale else None)))
    return ud


def varer(navn: str) -> list[str]:
    """Gruppens varer til prompten (uden '='-mærker)."""
    return [o.lstrip("=") for o in GRUPPER[navn][0]]


def rammer(tekst: str, navn: str) -> str | None:
    """Første vare fra gruppen i tekst (én ingrediens), eller None hvis den er fri for det."""
    ord_, undtag, fri = GRUPPER[navn]
    if any(f in str(tekst or "").lower() for f in fri):
        return None
    return find(tekst, ord_, undtag)


def find(tekst: str, ord_: list[str], undtag: list[str] = ()) -> str | None:
    """Første ord fra listen i tekst; undtagelser (fx 'tomatpasta') tæller ikke, '=ord' skal stå alene."""
    t = " " + str(tekst or "").lower() + " "
    for u in sorted(undtag, key=len, reverse=True):
        t = t.replace(u, " ")
    for o in ord_:
        if o.startswith("="):
            if re.search(rf"(?<!\w){re.escape(o[1:])}(?!\w)", t):
                return o[1:]
        elif o in t:
            return o
    return None


# Kød og fisk - så koden selv kan se, om en ret er vegetar- eller fiskeret (en svag AI tager fejl).
_KOED = GRUPPER["rødt kød"][0] + GRUPPER["fjerkræ"][0] + ["kød", "frikadelle", "kotelet", "kebab", "gyros", "spegepølse"]
_KOED_UNDTAG = GRUPPER["rødt kød"][1] + ["kødfri", "sojakød", "vegetarkød", "plantekød", "vegetarfrikadelle"]
FISK = GRUPPER["fisk"][0] + GRUPPER["skaldyr"][0] + GRUPPER["bløddyr"][0]
# Smagsgivere, der ikke gør retten til en fiskeret (men heller ikke vegetar).
FISK_UNDTAG = ["fiskesauce", "fiskefond", "østerssauce", "ansjos", "rejechips", "østershat", "østerssvamp"]
_IKKE_KOED = ("vegetar", "vegansk", "plantebaseret", "plantefars")


def er_koed(tekst: str) -> str | None:
    if any(f in str(tekst or "").lower() for f in _IKKE_KOED):
        return None
    return find(tekst, _KOED, _KOED_UNDTAG)


def er_fisk(tekst: str, smag_taeller: bool = False) -> str | None:
    """Fisk/skaldyr i teksten. smag_taeller=True: også fiskesauce o.l. (til vegetar-tjekket)."""
    if any(f in str(tekst or "").lower() for f in _IKKE_KOED):
        return None
    return find(tekst, FISK + (["fiskesauce", "fiskefond", "østerssauce"] if smag_taeller else []),
                [] if smag_taeller else FISK_UNDTAG)
