# Blöjkalkylatorn 🍼

Ett litet Python-program som hämtar aktuella blöjpriser (Libero, Pampers m.fl.)
från svenska nätbutiker och testar kuponger/rabatter för att räkna fram
**billigaste priset per blöja (kr/blöja)**.

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
# Jämför alla blöjor i Willys och Apotea (utan kuponger)
python3 blojkalkylatorn.py

# Bara Libero
python3 blojkalkylatorn.py --marke Libero

# Bara Pampers, visa fler rader
python3 blojkalkylatorn.py --marke Pampers --topp 40

# Alla sex butikerna (Willys, Hemköp, Apotea, Coop, Apoteket, ICA)
python3 blojkalkylatorn.py --butiker willys,hemkop,apotea,coop,apoteket,ica

# ICA med din lokala butik (priserna skiljer sig mellan butiker!)
python3 blojkalkylatorn.py --butiker ica --ica-butik "maxi stockholm"
```

Programmet sorterar alltid på **billigast kr/blöja** överst.

## Testa kuponger/rabatter

### 1) Snabbkuponger direkt i terminalen

```bash
# 20 % rabatt på allt
python3 blojkalkylatorn.py --procent 20

# 10 kr rabatt per förpackning
python3 blojkalkylatorn.py --fast 10

# "Köp 3, betala för 2"
python3 blojkalkylatorn.py --kop-betala 3/2

# Flera kuponger samtidigt (de staplas)
python3 blojkalkylatorn.py --marke Libero --procent 20 --kop-betala 3/2
```

### 2) En kupongfil (mer kontroll – kan rikta kupongen mot märke/butik)

Redigera `kuponger.json` och kör med `--kuponger`:

```bash
python3 blojkalkylatorn.py --kuponger kuponger.json
```

Kupongtyper i filen:

| typ          | varde / fält         | betydelse                              |
|--------------|----------------------|----------------------------------------|
| `procent`    | `varde: 20`          | 20 % rabatt                            |
| `fast`       | `varde: 15`          | 15 kr rabatt per förpackning           |
| `kop_betala` | `kop: 3, betala: 2`  | köp 3, betala för 2                    |

Valfria begränsningar per kupong:
- `marke` – gäller bara det märket (t.ex. `"Libero"`).
- `butik` – gäller bara den butiken (t.ex. `"Apotea"`).

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
- **ICA** – söksidan är serverrenderad HTML med både pris och jämförpris (kr/st).
  Kräver att man väljer butik. Hämtas automatiskt via en riktig webbläsare
  (Playwright) för att ta sig förbi ICA:s bot-skydd (AWS WAF).

## Begränsningar / bra att veta

- **ICA har bot-skydd (AWS WAF).** Programmet kringgår det med en riktig
  webbläsare (Playwright) som löser JavaScript-utmaningen automatiskt. Utan
  Playwright (eller med `--ica-http`) faller det tillbaka på vanlig HTTP, som
  ibland blockeras. Webbläsaren renderar söklistan lat – antalet produkter kan
  därför bli något färre än på webben.
- **Utforskade men inte implementerade butiker:** Mathem (Next.js/Sanity) och
  City Gross (React-SPA) har komplexa eller obfuskerade API:er, och ÖoB blockeras
  av Cloudflare. Arkitekturen är gjord så att nya butiker är lätta att lägga till
  (en funktion per butik som returnerar en lista `Product`).
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
