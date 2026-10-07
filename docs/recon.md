# Recon (etap 0) – 2026-10-07

Sprawdzone na żywo z User-Agentem `radomsko-events/1.0`, ~1 żądanie/s na domenę. Surowe `robots.txt` w `tests/fixtures/robots/`, próbki odpowiedzi w `tests/fixtures/<źródło>/`. Fixtury zawierają same fakty (bez opisów i obrazów).

Stabilność: 1 = kruche, 5 = oficjalne API.

## Tabela źródeł

| Źródło | URL | robots.txt | Format danych | Stab. | Decyzja | Uwagi |
|---|---|---|---|---|---|---|
| MDK Radomsko | `mdkradomsko.pl/wp-json/wp/v2/pec-events` | `Disallow:` (pusty), tylko Yoast | REST JSON, 1192 wpisów w sumie | 5 | **adapter (1.)** | Patrz „MDK” niżej. |
| radomsko.pl (kalendarz miejski) | `www.radomsko.pl/component/ajax/?module=rdkcal&format=raw&method=getEventsByRange&start=…&end=…&label=x&tag_id=1424` | `Allow: /` | Fragment HTML (`mod_rdkcal`, Joomla) | 3 | **adapter (3.)** | Brak roku w karcie daty, rok trzeba wziąć z zakresu zapytania. |
| Muzeum Regionalne | `muzeum.radomsko.pl/wp-json/wp/v2/posts` | `Disallow:` (pusty) | WP REST: posty, termin tylko w tytule/tekście | 3 | **adapter heurystyczny** (`confidence=low`) | Brak typu wydarzeń. Tylko `posts` i `feed/`. |
| MBP Radomsko | `mbp-radomsko.pl/?format=feed&type=rss` | blokuje tylko katalogi systemowe Joomla | RSS 2.0, daty w tekście | 3 | **adapter heurystyczny** (`confidence=low`) | Kategoria `aktualnosci/wydarzenia`. |
| biletyna.pl | `biletyna.pl/Radomsko` | `Disallow` m.in. `/event/view/`, `/ajax/`; `Content-Signal: ai-train=no, search=yes` | JSON-LD (`MusicEvent`, `TheaterEvent`, `ComedyEvent`), 22 zdarzeń na stronie | 4 | **adapter (2., wspólny parser)** | Pobieramy tylko listing miasta i nie wchodzimy na `/event/view/`. Treści `ai-train=no` nie są dla nas przeszkodą: nie trenujemy modeli, zapisujemy tylko fakty. |
| radomskoogloszenia.pl/wydarzenia | `radomskoogloszenia.pl/wydarzenia` | `Allow: /`, `Disallow: /api/`; `ClaudeBot` ma `Allow: /` | JSON-LD `Event`, 28 zdarzeń | 3 | **pominąć** (regulamin XIII.2) | Zawiera też zdarzenia z wrzesień 2026 (przeszłe). Dane z bilety kupbilecik. Regulaminu nie sprawdzałem. `feed.xml` to ogłoszenia, nie wydarzenia. |
| ebilet.pl, strona miejsca | `www.ebilet.pl/miejsce/klub-muzyczny-bogart-w-gomunicach` | `Disallow: /api/ /cms/ /mobile-events/` | JSON-LD `Event` | 4 | **adapter per miejsce** | Strona miasta (`/miasto/gomunice`) jest szumem: trasy koncertowe po wielu miastach w jednym wpisie (`Elbląg, Gdańsk, Gomunice i inne`). Używać stron `/miejsce/…`. Daty bez strefy (lokalne). |
| naszemiasto.pl | `radomsko.naszemiasto.pl/kalendarz-imprez/` | `*: Allow /`, ale blokuje m.in. `ClaudeBot`, `GPTBot` | – | – | **pominąć** | Odpowiada **HTTP 403** na nasz UA. Nie omijamy blokady. |
| atrakcje.pl | `atrakcje.pl/radomsko` | `Allow: /` | – | – | **do ponownego sprawdzenia** | `/radomsko` zwraca 404. Nie znalazłem poprawnego adresu kalendarza miejscowości. |
| kamiensk.pl | `kamiensk.pl/kalendarz/DD-MM-RRRR` | **brak** (zwraca HTML strony głównej) | HTML, tabela Godzina/Miejsce/Tytuł/Kategoria | 3 | **adapter (po zdecydowaniu)** | Format dat to `DD-MM-RRRR`, **nie** `RRRR-MM-DD` jak w CLAUDE.md. W dniu testu brak wydarzeń, więc struktury niepustego dnia nie widziałem. Brak robots.txt traktuję ostrożnie. |
| MDK Przedbórz | `www.mdk.przedborz.pl/kalendarz/RRRR-MM-DD/<id>` | 404 (brak reguł) | HTML, brak JSON-LD | 2 | **adapter lub ręcznie** | Przedbórz (30,7 km) włączony jawnie decyzją użytkownika. |
| gomunice.pl (Klub Bogart) | `gomunice.pl/informator/kalendarz` | `Disallow` tylko parametr `?iccaldate=` i katalogi Joomla, **`Crawl-delay: 10`** | iCagenda, w statycznym HTML brak linków do wydarzeń | 1 | **ręcznie** (wg decyzji z CLAUDE.md) | **Sprzeczność:** CLAUDE.md mówi, że gomunice.pl blokuje roboty, a robots.txt tego nie potwierdza. Strona nie blokuje robotów, ale nie wystawia wydarzeń w statycznym HTML. Wydarzenia Klubu Bogart bierzemy z ebilet. |
| radomszczanska.pl | – | blokuje m.in. `/user/`, `/grupa/`, boty AI | – | – | **ręcznie** (podpowiedzi) | Nie sprawdzałem struktury. |
| radomsko.org | – | HTTP 502 (Bad Gateway) | – | – | **ręcznie / brak danych** | Serwis nie odpowiadał w czasie testu. |
| inforadomsko.pl | – | `Disallow:` (pusty), Yoast | – | – | **ręcznie** (podpowiedzi) | WordPress, nie badałem `wp-json`. |

## MDK Radomsko (szczegóły, najlepsze źródło)

- `GET /wp-json/wp/v2/pec-events?per_page=100` zwraca pola strukturalne: `pec_date` (`YYYY-MM-DD HH:MM:SS`, czas lokalny), `pec_end_date`, `pec_end_time_hh/mm`, `pec_all_day`, `pec_location`, `pec_link`, `pec_recurring_frecuency`, `pec_extra_dates`, `pec_exceptions`, `pec_events_category` (id), `link`, `modified`.
- Nagłówki `x-wp-total` (1192) i `x-wp-totalpages` pozwalają stronicować.
- **Brak filtra po `pec_date` w REST**, więc trzeba pobierać wg `orderby=modified&order=desc` (albo po `date`) i filtrować po stronie klienta `pec_date >= dziś`. Ze 100 ostatnio zmodyfikowanych wpisów 25 miało przyszłą datę. Wydarzenie dodane dawno temu na odległy termin może mieć starą `modified`, więc trzeba stronicować głębiej lub użyć sitemapy (`pec-events-sitemap.xml`, `…2.xml`, z `lastmod`).
- Kategorie (id → nazwa): 32 Kino (154), 33 Teatr, 36 Muzyka, 38 Wystawy, 39 Inne, 108 zajęcia itd. Kategoria 32 → `kino` (rollup). Pozostałe → `scena`/`edukacja`/`inne`.
- Tytuły zawierają prefiks z datą (`31.12.2026r.- …`), który trzeba obciąć przy normalizacji (ważne dla dedupe).
- `pec_date` o godzinie `00:00:00` często znaczy „brak godziny”, nie północ.
- Linki do biletów są **tylko w treści** (`content.rendered`): `mdkradomsko.bilety24.pl`, `bilety24.pl`, `biletyna.pl`, a część z parametrami śledzącymi (`gclid`, `utm_*`), które trzeba obciąć. Fixture ma wyciągnięte `_ticket_urls`.
- `pec_venue_map_lnlat` i `pec_location` są puste w próbce, więc miejscem jest domyślnie MDK.

## radomsko.pl (widżet `mod_rdkcal`)

- Endpoint: `/component/ajax/?module=rdkcal&format=raw&method=<m>`. Metody znalezione w `rdkcal.js`: `getCalendarData` (`month`, `tag_id`, `week_start`, `show_past`), `getEventsByDate` (`date`, `tag_id`), `getEventsByRange` (`start`, `end`, `label`, `tag_id`), `getEventDetails` (`id`).
- Zakres 2026-10-01…12-31 dał 8 wydarzeń, głównie MDK, Noc Bibliotek, MBP. Duże pokrycie z MDK (do deduplikacji).
- Odpowiedź to HTML: dzień i skrót miesiąca (`PAŹ`), godziny `18:00–19:00`, tytuł, `data-id`. **Brak roku** w karcie.
- Parametry zapytania inne niż w `rdkcal.js` kończą się błędem `LogicException` (404).

## Gminy w promieniu 30 km (`data/venues.yaml`)

Wyliczone programowo: Wikidata SPARQL (siedziby gmin, P625), haversine od (51.0670 N, 19.4450 E). Odległość dotyczy **siedziby gminy**, nie obiektu kultury.

- W progu ≤ 30 km: 25 gmin (łącznie z Radomskiem), m.in. Ładzice 6,6; Dobryszyce 9,2; Gomunice 11,4; Lgota Wielka 11,6; Kobiele Wielkie 12,6; Gidle 13,1; Kodrąb 13,3; Kamieńsk 15,3; Kruszyna 16,7; Kłomnice 17,2; Nowa Brzeźnica 18,7; Kleszczów 19,5; Gorzkowice 19,6; Żytno 20,1; Sulmierzyce 22,0; Strzelce Wielkie 22,4; Wielgomłyny 23,1; Masłowice 24,2; Mykanów 24,8; Dąbrowa Zielona 25,6; Rędziny 28,3; Łęki Szlacheckie 28,6; Mstów 28,8; Rozprza 29,5.
- **Przedbórz: 30,7 km, poza progiem 30 km**, ale włączony decyzją użytkownika (`force_include`). Przyrów (30,1) i Ręczno (31,6) zostają poza zasięgiem.
- Strony urzędów znalazłem (potwierdzone, że odpowiadają i tytuł pasuje) dla większości gmin. Nie znalazłem: Strzelce Wielkie, Kodrąb, Żytno, oficjalnych głównych stron Dobryszyc i Ładzic (jest BIP / `ladzice.pl`). Kobiele Wielkie i Wielgomłyny to portale `samorzad.gov.pl`.

## Zweryfikowane vs niezweryfikowane

**Zweryfikowane na żywo:** `robots.txt` dla 15 domen (radomsko.org: 502; kamiensk.pl: brak pliku; mdk.przedborz.pl: 404), `wp-json` MDK i Muzeum, endpoint `rdkcal`, obecność JSON-LD `Event` na biletynie, radomskoogloszenia i ebilet, RSS MBP, odległości.

**Nie udało się / nie zrobiłem:**
- Regulaminów (ToS) serwisów: biletyna, ebilet, radomskoogloszenia, kupbilecik. **Wymaga Twojej decyzji prawnej** przed włączeniem adapterów agregatorów, zgodnie z CLAUDE.md.
- GOK/MOK/biblioteki dla gmin: zgadywanie domen nie dało trafień. Wymaga wyszukiwania ręcznego/webowego (nieweryfikowane). Poza MDK, Muzeum, MBP i Bogartem nie mam żadnej instytucji kultury z gmin.
- Kłomnice (GOK), Kobiele Wielkie, Ładzice: strony urzędów istnieją, ale nie przeglądałem ich pod kątem kalendarza.
- Niepuste dni na kamiensk.pl i struktura wydarzeń na mdk.przedborz.pl (tylko jedna strona wydarzenia).
- Dokładne współrzędne obiektów (w `venues.yaml` `lat/lon: null`).
- Realna deduplikacja i zgodność stref (bilety: biletyna ma offset, ebilet i radomskoogloszenia różnie).

## Proponowana kolejność adapterów

1. **MDK Radomsko** (REST). Najbogatsze dane i wspólne pole dla kina.
2. **Wspólny parser JSON-LD** i nakładki: ebilet (`/miejsce/…`), biletyna (Radomsko, warunkowo).
3. **radomsko.pl `rdkcal`** (uzupełnienie, część duplikuje MDK).
4. **MBP (RSS)** i **Muzeum (WP posts)**: parser heurystyczny dat, `confidence=low`.
5. **Kamieńsk, Przedbórz**: po rozpoznaniu niepustych stron.
6. **Ręczny plik** `manual_events.yaml` (Gomunice, plakaty, reszta gmin).

## Ryzyka

- **MDK:** brak filtra po dacie wydarzenia, a REST może zmienić strukturę wtyczki Pro Event Calendar. Linki do biletów tylko w treści HTML.
- **Daty:** MDK w czasie lokalnym bez strefy, ebilet bez offsetu, biletyna z offsetem. Trzeba ujednolicić do Europe/Warsaw.
- **Duplikaty:** to samo wydarzenie z MDK, biletyny, radomsko.pl i kupbilecik (prefiks daty w tytule MDK psuje dopasowanie).
- **Kino w MDK:** 154 wpisów kategorii „Kino”, rollup potrzebny od razu.
- **Heurystyczne daty** z tytułów Muzeum/MBP (fałszywe trafienia).
- **Regulaminy/prawo** agregatorów, `ai-train=no` w sygnałach treści (nie trenujemy, ale to wymaga Twojej akceptacji).
- **Wydajność odpowiedzi** MDK (duże `content.rendered`): używać `_fields`.
- **Odległość:** liczona od siedziby gminy, a nie obiektu; miejsce w mieście wydarzenia trzeba mapować w `venues.yaml`.

## Regulaminy agregatorów (sprawdzone 2026-10-07)

- **ebilet.pl** (`/regulamin`): jedyny zakaz dotyczy botów kupujących bilety. Zakazu pobierania danych o wydarzeniach nie znalazłem. Decyzja: **adapter OK**, tylko strony `/miejsce/…`, linkujemy do ebilet.
- **radomskoogloszenia.pl** (`/content/regulamin`): pkt XIII.2 zabrania kopiowania i przechowywania „artykułów, opisów, zdjęć oraz wszelkich innych treści” bez pisemnej zgody, a pkt VI zakazuje nadmiernego obciążania serwera. Ten sam serwis w `llms.txt` pozwala cytować treści z podaniem źródła. Przechowujemy tylko fakty, ale zapis jest szeroki i niejednoznaczny. Decyzja: **pominąć** (wydarzenia z Radomska pokrywają MDK i biletyna).
- **biletyna.pl** (`/regulations/get/id/159`, „Regulamin portalu”, wersja z 2026-08-28, PDF, 6 stron, przeczytany w całości): dotyczy wyłącznie kont klientów, newslettera, programu poleceń i danych osobowych. **Brak zapisów o automatycznym dostępie, pobieraniu danych i prawach do treści listingu.** Regulaminu sprzedaży (id 389) nie czytałem, bo dotyczy zakupu biletów. Decyzja: **adapter OK** dla listingu `biletyna.pl/Radomsko` zgodnie z `robots.txt` (bez `/event/view/`, `/ajax/`), tylko fakty i link do biletyny.
- **kupbilecik.pl:** nie sprawdzałem. Używamy go tylko jako linku do biletów z JSON-LD radomskoogloszenia, które pomijamy.

## Decyzje użytkownika (2026-10-07)

1. Przedbórz włączony do zasięgu (`force_include: true` w `venues.yaml`, filtr w CLAUDE.md zaktualizowany).
2. Regulaminy sprawdzone, patrz wyżej. Regulamin portalu biletyny przeczytany, bez zastrzeżeń.
3. Gomunice zostaje „ręcznie”, Klub Bogart z ebilet.
4. CLAUDE.md poprawiony: format dat Kamieńska `DD-MM-RRRR`.
