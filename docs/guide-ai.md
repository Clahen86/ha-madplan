# Guide: Sæt AI op til Madplan (gratis med Google Gemini)

Madplan bruger en **AI Task** i Home Assistant til at finde på retterne. Den nemmeste og gratis løsning er Google Gemini. Det tager ca. 5 minutter.

## 1. Lav en gratis nøgle hos Google

1. Gå til **[aistudio.google.com](https://aistudio.google.com)** og log ind med en Google-konto.
2. Tryk **Get API key** (eller *Hent API-nøgle*) i menuen.
3. Tryk **Create API key** og vælg **Create API key in new project**.
   > Tip: Et nyt projekt kun til Madplan giver Madplan sin egen gratis kvote, så den ikke deler med fx stemmestyring.
4. Kopiér nøglen (en lang tekst, der starter med `AIza…`). Del den ikke med andre.

## 2. Sæt Gemini op i Home Assistant

1. Gå til **Indstillinger → Enheder og tjenester → Tilføj integration**.
2. Søg efter **Google Generative AI** og vælg den.
3. Indsæt nøglen og tryk **Send**.
4. Integrationen laver bl.a. en **AI Task**-enhed, fx `ai_task.google_ai_task`.
   > Tip: Omdøb den gerne til "Gemini Madplan", så du kan se, hvad den bruges til.

## 3. Vælg den i Madplan

- **Ny opsætning:** Vælg AI Task-enheden, når du tilføjer Madplan.
- **Allerede sat op:** Madplan → **Konfigurer** → vælg AI Task-enheden.

Tryk **Ny madplan** for at prøve.

## Godt at vide

- **Gratis kvote:** Googles gratis plan giver et begrænset antal kald om dagen (typisk ca. 20 pr. model). En ugeplan er ét kald, *Byt ret*, *Ekstra varer* og *Én ret* er ét kald hver – almindelig brug ligger langt under.
- **"Dagskvoten er brugt op":** Vent til næste dag (nulstilles ca. kl. 9 dansk tid). Madplan bruger ikke flere kald på at prøve igen.
- **Andre AI'er:** OpenAI og Anthropic virker også, hvis de er sat op som AI Task i Home Assistant (de koster penge).
