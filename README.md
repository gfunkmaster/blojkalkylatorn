# Blöjkalkylatorn 🍼

Ett litet Python-program som hämtar **riktiga, aktuella** blöjpriser (Libero,
Pampers m.fl.) från svenska nätbutiker och visar butikernas egna kampanjer, för
att hitta **billigaste priset per blöja (kr/blöja)**. Du kan även mata in egna
kuponger med villkor och få dem verifierade mot de riktiga produkterna.

## Krav

- Python 3.9 eller senare (finns redan på de flesta Macar).
- **Basfunktionen** (Willys, Hemköp, Apotea) behöver inga extra paket.
- **ICA via webbläsare** (kringgår ICA:s bot-skydd) kräver Playwright:

```bash
pip3 install --user playwright
python3 -m playwright install chromium
```

Om Playwright inte är installerat faller ICA automatiskt tillbaka på vanlig HTTP
(som fungerar ibland).

## Snabbstart

Öppna en terminal i den här mappen och kör:

```bash
# Jämför alla blöjor i Willys och Apotea
python3 blojkalkylatorn.py

# Bara Libero
python3 blojkalkylatorn.py --marke Libero

# Bara Pampers, visa fler rader
python3 blojkalkylatorn.py --marke Pampers --topp 40

# Alla åtta butikerna (Willys, Hemköp, Apotea, Coop, Apoteket, Mathem, City Gross, ICA)
python3 blojkalkylatorn.py --butiker willys,hemkop,apotea,coop,apoteket,mathem,citygross,ica

# ICA med din lokala butik (priserna skiljer sig mellan butiker!)
python3 blojkalkylatorn.py --butiker ica --ica-butik "maxi stockholm"
```

Programmet sorterar alltid på **billigast kr/blöja** överst.

## ★ Riktiga kampanjer

Programmet visar **riktiga, aktuella priser och erbjudanden** som hämtas
direkt från butikernas egna API:er.

Produkter med en pågående kampanj/erbjudande markeras med **★** i tabellen, och
längst ned listas alla med detaljer. Erbjudandena kan dock ha villkor:

- **Medlemskap** krävs ibland (t.ex. ICA Stammis, Coop Medlem, Willys+,
  City Gross medlemspris).
- **Minsta köp** (t.ex. "handla för 300 kr").
- **Giltighetstid** och **engångs-/flergångsrabatter**.

Vissa butiker (Apoteket, Mathem) lägger redan in kampanjpriset i priset som
visas, medan andra (t.ex. City Gross medlemspris) visas som en separat ★-rad.
Kontrollera alltid villkoret hos butiken innan du litar på priset.

### Exempel på utskrift

```
#  Butik       Pris/fp   Antal  kr/blöja  Märke   Produkt
1  City Gross  42,95 kr   24 st   1,79 kr  Libero  Comfort 1 2-5Kg
...
6  City Gross  99,95 kr   43 st   2,32 kr  Libero  Comfort 3 5-8Kg ★

★ Erbjudanden/kampanjer som butikerna visar just nu (kan kräva medlemskap
  eller minsta köp – oftast inte inräknade i priset ovan):
  ★ City Gross: Comfort 3 5-8Kg → 2500324255 (94.95 kr) [medlem]
```

## Verifiera egna kuponger

Du kan mata in en **riktig kupong** med dess villkor i `kuponger.json` och köra
med `--kuponger`. Programmet filtrerar då fram rätt produkter (märke + storlek),
räknar ut priset och **visar alla villkor tydligt** så att du kan kontrollera dem.

### Kupongens villkor (du fyller i dem själv)

| Fält           | Betydelse                                                        |
|----------------|------------------------------------------------------------------|
| `beskrivning`  | T.ex. "20 % på Libero Comfort strl 4"                            |
| `typ`          | `procent`, `fast` (kr) eller `kop_betala`                        |
| `varde`        | Procent (20) eller kr (15)                                       |
| `kop`/`betala` | För `kop_betala`: köp X, betala Y                                |
| `kalla`        | **Var kommer den ifrån?** (ICA Stammis, Coop Medlem, reklamblad…) |
| `marke`        | Vilket märke den gäller (t.ex. `Libero`)                         |
| `storlek`      | Vilken storlek (matchas mot produktnamnet, t.ex. `Comfort 4`)     |
| `minsta_kop`   | Minsta köp i kr (gäller hela korgen)                             |
| `endast_medlem`| Kräver medlemskap (true/false)                                   |
| `giltig_till`  | Giltig till datum (t.ex. `2026-12-31`)                           |
| `engangs`      | Engångsrabatt (true/false)                                       |
| `gallplats`    | `online`, `butik` eller `båda`                                   |

### Exempel på utskrift med kupong

```
Kuponger (med villkor att verifiera):
  • 20 % rabatt på Libero Comfort storlek 4
    └ Källa: Coop Medlem · Märke: Libero · Storlek: Comfort 4 · Minsta köp: 300 kr · Endast medlem · Giltig t.o.m. 2026-12-31 · Gäller: båda
```

Programmet kan **bara** filtrera på märke/storlek och räkna ut rabatten. De
övriga villkoren (källa, giltighet, medlemskrav, minsta köp, engångs, plats)
visas så att **du själv kontrollerar** att kupongen faktiskt är riktig och gäller
för ditt köp.

## Övriga flaggor

| Flagga                 | Betydelse                                              |
|------------------------|--------------------------------------------------------|
| `--sok`                | Sökord, kommaseparerat. Standard: `blöjor`             |
| `--butiker`            | Vilka butiker. Standard: `willys,apotea`               |
| `--marke`              | Filtrera på märke (`Libero`, `Pampers`)                |
| `--ica-butik`          | Välj ICA-butik via sökord (t.ex. `maxi stockholm`)      |
| `--ica-id`             | Välj ICA-butik via accountId direkt (t.ex. `1003723`)   |
| `--lista-ica-butiker`  | Lista ICA-butiker som matchar sökordet och avsluta      |
| `--ica-http`           | Tvinga ICA-hämtning via vanlig HTTP (utan webbläsare)    |
| `--kuponger`           | Sökväg till JSON-fil med kuponger (med villkor)          |
| `--topp`               | Antal rader att visa (standard 25)                     |
| `--max-sidor`          | Antal sök-sidor per butik (Apotea, standard 3)         |
| `--jmf-pris`           | Hämta officiellt jämförpris från Apoteas produktsidor   |
| `--visa-alla`          | Visa även produkter som inte är blöjor                 |

### Välja ICA-butik

ICA-priser skiljer sig mellan butiker, så välj din lokala butik. Först kan du
lista butiker som matchar ett sökord:

```bash
python3 blojkalkylatorn.py --lista-ica-butiker "maxi stockholm"
```

Sedan väljer du butiken:

```bash
python3 blojkalkylatorn.py --butiker ica --ica-butik "maxi stockholm"
# eller med accountId direkt:
python3 blojkalkylatorn.py --butiker ica --ica-id 1003418
```

## Så fungerar det

- **Willys** – söksidan svarar med ren JSON och innehåller officiellt
  *jämförpris* (kr/st) direkt.
- **Hemköp** – samma JSON-API som Willys (samma koncern, Axfood).
- **Apotea** – söksidan är serverrenderad HTML; programmet räknar ut kr/blöja
  från antalet i produktnamnet (t.ex. "24 st", "111 blöjor"). Med `--jmf-pris`
  hämtas dessutom det officiella jämförpriset från varje produktsida.
- **Coop** – har ett öppet personaliserings-API (`external.api.coop.se`) som ger
  pris, antal och jämförpris (kr/st) direkt. Använder Coops standardbutik online
  (`store=251300`).
- **Apoteket** – har ett sök-API (`apoteket-se.54proxy.com`) som ger pris, antal
  och kampanjpris direkt. Säljer Libero (och eget märke/Naty) men inte Pampers.
- **Mathem** – öppet sök-API (`/api/v1/search/mixed/`) som ger pris, antal och
  jämförpris (kr/st) direkt.
- **City Gross** – Loop54-sök-API (`/api/v1/Loop54/search`) som ger pris, antal
  och jämförpris (kr/st) direkt.
- **ICA** – söksidan är serverrenderad HTML med både pris och jämförpris (kr/st).
  Kräver att man väljer butik. Hämtas automatiskt via en riktig webbläsare
  (Playwright) för att ta sig förbi ICA:s bot-skydd (AWS WAF).

## Begränsningar / bra att veta

- **ICA har bot-skydd (AWS WAF).** Programmet kringgår det med en riktig
  webbläsare (Playwright) som löser JavaScript-utmaningen automatiskt. Utan
  Playwright (eller med `--ica-http`) faller det tillbaka på vanlig HTTP, som
  ibland blockeras. Webbläsaren renderar söklistan lat – antalet produkter kan
  därför bli något färre än på webben.
- **Utforskade men inte implementerade butiker:** ÖoB blockeras av Cloudflare.
  Arkitekturen är gjord så att nya butiker är lätta att lägga till (en funktion
  per butik som returnerar en lista `Product`).
- **Coop-API:et använder en prenumerationsnyckel** som ligger inbäddad i Coops
  egen webbfrontend (`ocp-apim-subscription-key`). Den kan ändras av Coop utan
  förvarning, vilket i så fall bryter Coop-hämtningen tills nyckeln uppdateras.
- Priserna är **onlinepriser** och kan skilja sig från din lokala butik (gäller
  särskilt ICA, där priset beror på vilken butik du väljer).
- Webbplatserna kan ändra sin struktur eller börja blockera hämtning. Om något
  slutar fungera kan man behöva uppdatera parser-reglerna.
- Vissa få Apotea-produkter saknar antal i namnet; de markeras och hoppas över
  i rankingen om inte `--jmf-pris` används.
- Hämta med måtta (programmet har inbyggd fördröjning mellan sidor) och respektera
  butikernas villkor.
