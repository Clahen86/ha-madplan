# Changelog – Madplan

Newest first. Each version lists what changed since the one before.

## 1.23.1 – 2026-11-24

- An ingredient the AI named by its offer id ("400 g 9J6SDCIVEVPUWof3Xbh-L") gets the product's real name - also in this week's plan, fixed at start without a new plan

## 1.23.0 – 2026-11-23

- "Move day": move a dish to another day of the week - the two days swap places. Same dishes, same shopping list, no new AI plan
- A dish made for 2 days moves together with its leftovers day
- Who cooks and the number of people stay with the day
- Can't move onto a day before the plan, into another dish's leftovers day, or a dish with short-dated food-waste items to a later day
- Also works from the adult app link
- Fixed: an "avoid" rule with more than one word (like "Mexican food") no longer warns on every dish that has a word ending like it - "mad" matched "madlavningsfløde". Only allergies also check the last word, and never common words like "food" or "cuisine"
- Short words in allergy and avoid rules (3 letters or less) only count at the start or end of a word: "ost" finds "hytteost" and "ostesauce" but not "rostbøf", "and" not "mandler", "is" not "ris", and "te" only as a word of its own

## 1.22.0 – 2026-11-22

- Better recipes: each dish is a whole dinner with its usual sides (roast pork with potatoes, gravy and red cabbage), steps with oven temperature and times (amounts stay in the ingredient list, so they follow the number of people), and enough meat or fish (125-175 g per person)
- Dishes are checked before the plan is shown, and sent back to be fixed when the name promises something that isn't in it ("with peas" without peas), there's under 100 g meat or fish per person, a roast is given too little time, or an item is too vague to buy ("Creme")
- After "Show detailed recipe" you can switch back to the short steps and forth again - no new AI call
- Ingredient names are cleaned up: no "S:" in front, no pack size in the name, never empty
- The number of people shows at once when you change it - also before a new plan
- "Creme" is now bought as crème fraîche, and an item is never matched on a describing word alone ("dried spices" became sun-dried tomatoes)

## 1.21.2 – 2026-11-22

- No more warning in Home Assistant's log at start-up (the version was read from disk in the event loop)

## 1.21.1 – 2026-11-21

- One dish: a new number of people shows right away (the page kept showing the old amounts)

## 1.21.0 – 2026-11-21

- One dish from the fridge can now do what a dish in the week plan can: swap it for another dish from the same fridge, show the detailed recipe, change the number of people (amounts and shopping are recalculated), save it as my dish, and send what is missing to the REMA app. It also shows kcal, protein, price per person and the health note
- Adult app links get the "One dish" tab too

## 1.20.0 – 2026-11-21

- App without login: choose "Children · view only" or "Adult · can control" when you make a link. An adult link can also make a new meal plan, swap or remove a dish, choose days, people and who cooks, add extra items and send the shopping list. Rules and settings are still only changed in Home Assistant

## 1.19.0 – 2026-11-18

- Madplan as an app without login, who cooks each day

## 1.18.2 – 2026-11-16

- Statistics: leftovers are counted from the plan (days with leftovers), not a rule that does not exist

## 1.18.1 – 2026-11-15

- Store and update links open right inside Home Assistant
- The budget is held against what you have to buy, and the store totals say they cover the whole week

## 1.18.0 – 2026-11-14

- Update card (new version, your error fixed) and the version in the daily question

## 1.17.1 – 2026-11-14

- Files under a new address for every version, so a browser never mixes old and new files

## 1.17.0 – 2026-11-14

- Suggestions of the other apps (fits your home, from the same developer)

## 1.16.2 – 2026-11-14

- A too long AI answer splits the week in two
- Another AI takes over when the chosen one doesn't answer
- Known AI problems aren't reported as app errors

## 1.16.1 – 2026-11-14

- Errors from Home Assistant restarting or the network (502, timeout, no connection) are not reported

## 1.16.0 – 2026-11-14

- Close on replies, replies disappear by themselves, asks every 10 minutes the first week

## 1.15.1 – 2026-11-14

- A new reply always gives a notification, even when the panel is open
- README

## 1.15.0 – 2026-11-14

- Message from the developer about an error

## 1.14.0 – 2026-11-14

- Replies from the developer under Help

## 1.13.2 – 2026-11-14

- The help button shows 'Help' with text so it is easy to see

## 1.13.1 – 2026-11-14

- Madplan could not start after 1.13.0 (the help was in the plans' shared lookup) - fixed
- The check buttons overlapped (class name collided with the item list's check circle)

## 1.13.0 – 2026-11-14

- Help and check (🛟) - Check meal plan (offers per chain, Salling, AI, notifications), Get help with message and images, Share anonymously what works (offers per chain, items the search did not find, errors) - never allergies, rules, recipes or lists

## 1.12.0 – 2026-11-09

- Profiles: the field for a new profile gets its own line
- Billede i README
- Leftovers - the meal plan calculates what is left of the packs, uses large leftovers in a later dish and shows days and remainder on the item

## 1.11.0 – 2026-11-09

- Profiles - own rules, dishes and plans per profile
- You see the profile your HA user belongs to

## 1.10.2 – 2026-11-09

- Shopping lists without a description (e.g. Shopping list, Bring) get the price after the item instead of failing

## 1.10.1 – 2026-11-08

- 'Show detailed recipe' also in the large recipe view (there are two)

## 1.10.0 – 2026-11-08

- All ingredients get an amount (otherwise 'to taste'), and 'Show detailed recipe' on each dish - thorough steps with amounts, temperatures and times, one AI call and saved

## 1.9.1 – 2026-11-07

- The notification check understands recipients outside notify
- Only the item's name on the buttons

## 1.9.0 – 2026-11-07

- 'We assume you have' at the top of Shopping (tap what you are missing), spice check for one dish, the kitchen cupboard is learned, number you have in the heading

## 1.8.1 – 2026-11-07

- 'Number of days' removed again - the weekdays under 'Plan is made for' do the same

## 1.8.0 – 2026-11-07

- Number of days (1-7), recipes are checked - what the steps mention must be on the ingredient list, and spices must have names

## 1.7.0 – 2026-11-06

- Madplan: send the shopping list to the REMA 1000 app (optional, with your own REMA account)
- Madplan: offer items are sent to the REMA app with item number from the catalog
- Ingen dobbelte antal ved gensending
- Madplan: own button for the REMA app (no email), items found from the dish name, organic only when stated
- Madplan: offers are sent to the REMA app as the item that has the offer price today and the right size
- Madplan: quantity is converted when the REMA app's item has a different size than the offer
- Madplan 1.7.0

## 1.6.4 – 2026-11-06

- Madplan: the food waste check now updates the list immediately (the attributes shared an object with the plan), check is logged
- Madplan: 'Shopping somewhere else?' - food waste is checked in another store in the chain today
- Madplan: swapped food waste items come back when they are in stock again (or when switching back to your store)
- Madplan: older swapped food waste items can also come back (found by name)
- Madplan: the store's food waste that fits the week's dishes is put in when it is cheaper (no AI, respects allergies)
- Madplan 1.6.4

## 1.6.3 – 2026-11-05

- Madplan: shorter food waste labels, warning when fewer are in stock, image in README
- Madplan: fewer food waste items in stock than the dish needs - the rest on its own line at regular price
- Madplan 1.6.3

## 1.6.2 – 2026-11-05

- Madplan 1.6.1: the AI builds 1-2 dishes around the food waste items, dinner items only, nice names
- Madplan: food waste shows when the item is used
- 'Freeze same day' only when used later
- Madplan: husker sidste butik, kortet hentes igen efter rettelser, ingen tomme madspild-billeder
- Madplan: picture of the same kind of item from the catalog when the main item has none (e.g. food waste)
- Madplan: sold-out food waste is automatically swapped for the regular item and price
- Madplan 1.6.2

## 1.6.1 – 2026-11-05

- Madplan 1.6.0: manglende import af IKKE_MAD
- Madplan: new store failed ("Value should be a list") when an older store had notify saved as text
- Madplan: one Salling key for all chains - new Netto/føtex/Bilka only ask for a store, and a new key is shared
- Madplan 1.6.1: shows why there are no food waste items (none in the store, not shopping today, none fit)

## 1.6.0 – 2026-11-05

- Madplan 1.6.0: food waste from Salling (extra reduced, short date) in the plan's first 2 days, live stock check on the shopping list, guide to the Food Waste API

## 1.5.5 – 2026-11-04

- Madplan 1.5.5: ready-made foods with hidden gluten/lactose (tzatziki, medister, pesto ...), help text about ingredient labels

## 1.5.4 – 2026-11-04

- Madplan 1.5.3: vegetarian/fish checked from the items, safer dish types and fixed days
- Madplan 1.5.4: items that break an allergy are swapped for a free variant
- Ellers byttes retten automatisk

## 1.5.3 – 2026-11-04

- Madplan 1.5.3: allergy groups (gluten, lactose, nuts and others) are explained to the AI and checked per item

## 1.5.2 – 2026-11-04

- Hassfest: help text without curly braces, sorted manifest
- Madplan 1.5.2: the prompt is built outside the event loop, README starts with HACS search

## 1.5.1 – 2026-11-03

- Madplan 1.5.1: own icon and automatic checks (hassfest, HACS)

## 1.5.0 – 2026-11-02

- New images: scrollable top menu, My dishes and kcal/protein
- Madplan 1.5.0: hele egne opskrifter i Mine retter

## 1.4.0 – 2026-11-02

- Madplan 1.4.0: scrollable top menu, My dishes and goals per serving

## 1.3.2 – 2026-11-02

- The automatic plan list shows all stores, even while HA is starting

## 1.3.1 – 2026-11-02

- Automatic plan: all added stores gathered in one list under Rules

## 1.3.0 – 2026-11-02

- Level (weekday/cozy/gourmet), repeat check, better allergy check, automatic plan on/off per store, optional limit for extra stores, 2000 characters in other requirements

## 1.2.3 – 2026-11-02

- More stores: the code switches to another chosen store when the same item is at least 10% cheaper per kg (at least 3 items per store)

## 1.2.2 – 2026-11-02

- More stores: per-kilo price comparison across the stores in the prompt, so the AI picks the cheapest

## 1.2.1 – 2026-11-02

- Flere butikker: ligestillede i prompten
- Another store is only used for at least 3 items, otherwise they are bought in the main store

## 1.2.0 – 2026-11-01

- More stores: also use offers from up to 2 other chains (e.g. REMA + Netto)
- The shopping list is split per store

## 1.1.0 – 2026-11-01

- Choose days, leftovers (cook for 2 days), household and cuisines, weekend time, reuse of items and more recipients

## 1.0.2 – 2026-11-01

- Choose shopping day (today / tomorrow) for a new meal plan
- Offers must apply that day

## 1.0.1 – 2026-11-01

- Guide for email (phone notification or Gmail via SMTP)
- Offers must only apply on the shopping day
- Saturday's plan waits until Sunday if next week's flyer is not out

## 1.0.0 – 2026-11-01

- Small fixes

## 0.11.5 – 2026-11-01

- Phone: the top stays within the screen
- Stores wrap onto several lines, all tabs are always visible

## 0.11.4 – 2026-11-01

- Fix: the page can be scrolled again on phones (removed touch-action and overflow: hidden)

## 0.11.3 – 2026-11-01

- Phone: store line and tabs scroll sideways by themselves without moving the page and keep their position

## 0.11.2 – 2026-11-01

- Each day in the weekly plan can be sent by email with shopping list and recipe

## 0.11.1 – 2026-11-01

- One dish can be sent by email
- Guides for AI (Gemini) and Salling key

## 0.11.0 – 2026-11-01

- New images and README: One dish, weekly plan from today, phone view
- Image for social preview (Facebook and others)
- Optional Salling prices: real prices in Netto, føtex and Bilka with the user's own key

## 0.10.4 – 2026-11-01

- Staples are decided by name: rice, pasta and vegetables do not start as 'have at home'

## 0.10.3 – 2026-11-01

- One dish: what the family has is matched on whole words, inflection, cuts and one typo

## 0.10.2 – 2026-11-01

- One dish: descriptive words (minced, fresh, Danish ...) do not count when deciding whether the family has an item

## 0.10.1 – 2026-11-01

- One dish: what the family has is decided from their own list
- The dish must use it

## 0.10.0 – 2026-11-01

- One dish from the fridge (new tab, separate from the weekly plan)
- Weekly plan midweek only from today
- Vegetarian and fish dishes default to 0

## 0.9.8 – 2026-11-01

- Swap dish keeps the rules: if the week lacks a fish or vegetarian dish, the new dish becomes that

## 0.9.7 – 2026-11-01

- Price box: 'approx.' moved below the amount so large amounts are not cut off on phones

## 0.9.6 – 2026-11-01

- Better room on phones: item rows with name and details separate, tabs with icon above text, smaller counters

## 0.9.5 – 2026-11-01

- Ikke-mad sorteres bedre fra
- Items whose subtitle is another kind of item are skipped
- Almindelig udgave frem for varianter

## 0.9.4 – 2026-11-01

- Stk/gram conversion for cabbage, fish, meat and bread
- Ukendt omregning = 1 pakke pr. ret
- At most 10 packs with a warning

## 0.9.3 – 2026-11-01

- Big chains: offers that are not dinner are filtered out of the meal plan prompt
- Fallback attempt with at most 150 offers

## 0.9.2 – 2026-11-01

- Short name list with staples instead of the whole range
- Vareopslag uden for event loop

## 0.9.1 – 2026-11-01

- Too long AI answer: one new attempt without the name list instead of five
- Kortere svar

## 0.9.0 – 2026-11-01

- The AI picks product names from REMA's name list
- Exact lookup before search

## 0.8.3 – 2026-11-01

- Better item search: fixed translations, real package sizes from offers, loose weight per kg

## 0.8.2 – 2026-11-01

- Wraps are found as tortillas
- Vegetables in pieces are converted to bags in grams

## 0.8.1 – 2026-11-01

- New images for README: phone mockups with headings
- Tjek AI'ens tilbuds-id mod ingrediensen
- Better search for frozen vegetables

## 0.8.0 – 2026-11-01

- Appearance and guests one day

## 0.7.0 – 2026-11-01

- Shopping: tap = in the basket, house button = have at home

## 0.6.0 – 2026-11-01

- Extra chips and the family's rules

## 0.5.0 – 2026-11-01

- The AI only gets offers
- Other items are looked up in the REMA catalog

## 0.4.0 – 2026-11-01

- New app design: tabs at the top, the store's colors, Tonight card and recipe page

## 0.3.2 – 2026-11-01

- Ekstra varer: altid 1 stk., brugeren justerer selv
- Madpakke-indstilling fjernet

## 0.3.1 – 2026-11-01

- Packed lunches per day, realistic amounts and +/- on extra items

## 0.3.0 – 2026-11-01

- Extra items: write a need, and the AI finds offers for the week on a separate list

## 0.2.0 – 2026-11-01

- App panel in the side menu, offers fetched per flyer, works for all 14 chains

## 0.1.1 – 2026-11-01

- Logic: offers, REMA prices, AI plan, item list, sensors and services
- Dashboard-kort: custom:madplan-card registreres automatisk
- More stores: one plan per chain, approximate prices outside REMA and new card design
- Honest prices: offer prices and approximate prices are shown separately
- Offers must apply on the shopping day
- New store inherits people and makes the first plan

## 0.1.0 – 2026-11-01

- Base package: config flow and HACS setup
