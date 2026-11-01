# Guide: Rigtige priser i Netto, føtex og Bilka (Salling Group-nøgle)

Uden nøgle viser Madplan **ca.-priser** for varer, der ikke er på tilbud i Netto, føtex og Bilka. Med en gratis nøgle fra Salling Group får du **rigtige priser fra din egen butik**. Det er helt valgfrit og tager ca. 10 minutter.

## 1. Opret en profil

1. Gå til **[developer.sallinggroup.dev](https://developer.sallinggroup.dev)**.
2. Log ind eller opret en gratis **Salling Group-profil** (der kræves ikke betalingskort).

## 2. Bed om adgang til tre API'er

Gå til **API-kataloget** (*Available APIs*). Tryk **Request access** på hver af disse:

- **Stores API**
- **Salling Group Products EAN API**
- **Salling Group Recommendations API**

For hver af dem:
1. Under **Environments**: vælg **Production**.
2. Under **Operations**: sæt flueben ved **alle** linjer.
3. Tryk på knappen nederst for at gemme.

Under **My API Collection** skal der nu stå **Granted** ved alle tre.

## 3. Opret en "application" og hent nøglen

1. Gå til **Applications** og tryk **Create a new application**.
2. Udfyld:
   - **Name:** `Madplan`
   - **Description:** `Madplan til Home Assistant`
   - **Type:** **Backend / Integration App**
3. Under **Scope**: sæt flueben ved **alle** linjer under de tre API'er.
4. Gem. Nu vises din **API key** – kopiér den. Del den ikke med andre.

> Har du tilføjet et API efter, at du lavede din application, så sæt flueben ved det under *Scope* – eller lav en ny nøgle.

## 4. Indsæt nøglen i Madplan

1. I Home Assistant: **Indstillinger → Enheder og tjenester → Madplan** → vælg **Netto**, **føtex** eller **Bilka** → **Konfigurer**.
2. Indsæt nøglen i **Salling Group-nøgle** og tryk **Send**.
3. Vælg **din butik** på listen (butikkerne nærmest hjemmets placering i Home Assistant).
4. Tryk **Ny madplan**. Priserne er nu fra din egen butik, og "ca." forsvinder for de fleste varer.

## Godt at vide

- Har du flere af kæderne, sættes nøglen på hver af dem (samme nøgle kan bruges).
- Varer, der ikke er blandt kædens ca. 1.000 mest købte, får stadig en ca.-pris.
- **"Nøglen virkede ikke":** Tjek at alle tre API'er står som *Granted*, og at de er valgt under *Scope* på din application.
- Kan Salling ikke svare, bruger Madplan ca.-priser og viser en advarsel – planen bliver altid lavet.
- Nøglen er din egen og til ikke-kommerciel brug. Vil du stoppe, så slet nøglen under **Konfigurer**.
