# Guide: Rigtige priser i Netto, føtex og Bilka (Salling Group-nøgle)

Uden nøgle viser Madplan **ca.-priser** for varer, der ikke er på tilbud i Netto, føtex og Bilka. Med en gratis nøgle fra Salling Group får du **rigtige priser fra din egen butik** – og kan bruge **madspild-varer** (ekstra nedsat, kort dato). Det er helt valgfrit og tager ca. 10 minutter.

> **Har du allerede en nøgle?** Spring til [Madspild med en nøgle, du allerede har](#madspild-med-en-nøgle-du-allerede-har).

## 1. Opret en profil

1. Gå til **[developer.sallinggroup.dev](https://developer.sallinggroup.dev)**.
2. Log ind eller opret en gratis **Salling Group-profil** (der kræves ikke betalingskort).

## 2. Bed om adgang til API'erne

Gå til **API-kataloget** (*Available APIs*). Tryk **Request access** på hver af disse:

- **Stores API**
- **Salling Group Products EAN API**
- **Salling Group Recommendations API**
- **Food Waste API** (kan også hedde *Anti Food Waste*) – kun nødvendig, hvis du vil bruge madspild

For hver af dem:
1. Under **Environments**: vælg **Production**.
2. Under **Operations**: sæt flueben ved **alle** linjer.
3. Tryk på knappen nederst for at gemme.

Under **My API Collection** skal der nu stå **Granted** ved dem alle.

## 3. Opret en "application" og hent nøglen

1. Gå til **Applications** og tryk **Create a new application**.
2. Udfyld:
   - **Name:** `Madplan`
   - **Description:** `Madplan til Home Assistant`
   - **Type:** **Backend / Integration App**
3. Under **Scope**: sæt flueben ved **alle** linjer under API'erne.
4. Gem. Nu vises din **API key** – kopiér den. Del den ikke med andre.

> Har du tilføjet et API efter, at du lavede din application, så sæt flueben ved det under *Scope* – eller lav en ny nøgle.

## 4. Indsæt nøglen i Madplan

1. I Home Assistant: **Indstillinger → Enheder og tjenester → Madplan** → vælg **Netto**, **føtex** eller **Bilka** → **Konfigurer**.
2. Indsæt nøglen i **Salling Group-nøgle** og tryk **Send**.
3. Vælg **din butik** på listen (butikkerne nærmest hjemmets placering i Home Assistant).
4. Tryk **Ny madplan**. Priserne er nu fra din egen butik, og "ca." forsvinder for de fleste varer.

## 5. Slå madspild til (valgfrit)

I Madplan: **Regler** → slå **Madspild** til. Fra næste madplan bruges 1-2 ekstra nedsatte varer fra din butik i de første 2 dage, og indkøbslisten viser, om de stadig er der.

## Madspild med en nøgle, du allerede har

Du kan beholde din nøgle – der skal ikke indsættes noget nyt i Home Assistant.

1. På **[developer.sallinggroup.dev](https://developer.sallinggroup.dev)**: tryk **Request access** på **Food Waste API** → **Production** → flueben ved alle **Operations** → gem.
2. Gå til **Applications** → din **Madplan**-application → sæt flueben ved **Food Waste** under **Scope** → gem.
3. Slå **Madspild** til under **Regler** i Madplan.

## Godt at vide

- **Én nøgle til alle:** har du sat nøglen ind i én af kæderne, bruger Netto, føtex og Bilka den automatisk. Tilføjer du en ny af dem, skal du kun vælge din lokale butik.
- Varer, der ikke er blandt kædens ca. 1.000 mest købte, får stadig en ca.-pris.
- **"Nøglen virkede ikke":** Tjek at API'erne står som *Granted*, og at de er valgt under *Scope* på din application.
- **Madspild kommer ikke med:** Tjek at *Food Waste API* står som *Granted* og er valgt under *Scope*. Madspild bruges kun, når der handles i dag eller i morgen, og kun hvis butikken har nedsatte madvarer lige nu.
- **Madspild-varer kan blive udsolgt** – retten virker altid med den almindelige vare.
- Kan Salling ikke svare, bruger Madplan ca.-priser og viser en advarsel – planen bliver altid lavet.
- Nøglen er din egen og til ikke-kommerciel brug. Vil du stoppe, så slet nøglen under **Konfigurer**.
