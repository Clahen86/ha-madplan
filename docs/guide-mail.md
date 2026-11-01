# Guide: Få madplanen og indkøbslisten på mail

Madplan kan sende ugens indkøbsliste, én dag fra ugeplanen eller **Én ret** på mail. Det bruger en **notify-tjeneste** i Home Assistant. Der er to muligheder:

## Mulighed A: Som besked på telefonen (nemmest)

Har du **Home Assistant-appen** på telefonen, findes der allerede en notify-tjeneste, fx `notify.mobile_app_din_telefon`.

1. Madplan → **Konfigurer** → skriv `notify.mobile_app_din_telefon` i **Notify-service til mail**.
   > Find det præcise navn under **Udviklerværktøjer → Handlinger** – søg på `notify.mobile_app`.
2. Gem. Så kommer listen som en besked på telefonen.

## Mulighed B: Som rigtig mail (Gmail)

### 1. Lav en app-adgangskode hos Google
Google kræver en særlig adgangskode til andre programmer:
1. Slå **totrinsbekræftelse** til på din Google-konto (hvis den ikke allerede er det).
2. Gå til **[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)**, skriv fx "Home Assistant" og tryk **Opret**.
3. Kopiér den 16-cifrede kode. Del den ikke med andre.

### 2. Gem koden i `secrets.yaml`
Åbn `secrets.yaml` (via File editor eller Studio Code Server) og tilføj:
```yaml
gmail_app_password: "din 16-cifrede kode"
```

### 3. Sæt mail-tjenesten op i `configuration.yaml`
Tilføj (eller udvid din eksisterende `notify:`):
```yaml
notify:
  - name: madplan_mail
    platform: smtp
    server: smtp.gmail.com
    port: 587
    encryption: starttls
    timeout: 15
    sender: din@gmail.com
    sender_name: Madplan
    username: din@gmail.com
    password: !secret gmail_app_password
    recipient:
      - din@gmail.com
```
Flere modtagere? Tilføj flere linjer under `recipient:`.

### 4. Genstart og vælg den i Madplan
1. **Udviklerværktøjer → Tjek konfiguration**, og genstart derefter Home Assistant.
2. Madplan → **Konfigurer** → skriv `notify.madplan_mail` i **Notify-service til mail** → Gem.

## Hvad kan sendes?
- **Send indkøbsliste** (Indkøb-fanen): hele ugens manglende varer, ekstra varer og opskrifter.
- **Send på mail** under **Opskrift**: kun den dags ret – varer, ingredienser og fremgangsmåde.
- **Send på mail** under **Én ret**: kun det, der mangler til retten, og opskriften.

Knapperne til mail vises først, når der er valgt en notify-tjeneste under **Konfigurer**.

## Hvis det ikke virker
- **"Username and Password not accepted":** Brug app-adgangskoden – ikke din normale Gmail-adgangskode.
- **Ingen knap "Send på mail":** Tjek at notify-tjenesten er udfyldt under Konfigurer, og genindlæs Madplan.
- Andre mailudbydere virker også – brug deres SMTP-server og port i stedet for Gmails.
