# CLAUDE.md – Radomsko Events

Codziennie aktualizowany kalendarz wydarzeń kulturalnych, społecznych i edukacyjnych w Radomsku i do 30 km od niego. Statyczna strona (GitHub Pages), dane w JSON, subskrypcja ICS, poranny digest przez ntfy. Repozytorium jest **publiczne**.

## Decyzje projektowe (ustalone, nie zmieniaj bez pytania)
- Hosting: GitHub Actions (cron) + GitHub Pages. Brak serwera i bazy danych.
- Kanały: ICS (`events.ics`) i push przez ntfy.sh. Bez e-maila.
- Zasięg: Radomsko plus miejscowości do 30 km (odległość liczona programowo od centrum Radomska, haversine). Priorytet: Gomunice (Klub Bogart), Kamieńsk, Kłomnice, Kobiele Wielkie, Ładzice, Przedbórz (30,7 km od centrum, włączony jawnie przez `force_include: true` w `venues.yaml`).
- Kino: seanse zwijane do jednej pozycji na film (zakres dat, lista godzin w polu `times`), kategoria `kino`.
- Digest: „dziś”, „najbliższe 7 dni” oraz „nowo dodane” od poprzedniego dnia; dostarczany o 7:00 (dane z poprzedniego wieczoru).
- Wydarzenia po dacie zakończenia są usuwane z `events.json` i `events.ics` (historia zostaje w git).

## Stos
Python 3.12, `httpx`, `selectolax`, `pydantic`, `rapidfuzz`, `icalendar`, `pyyaml`, `pytest`, `ruff`. Frontend: statyczny HTML, CSS i vanilla JS, bez frameworka i bez kroku build. Dokumentacja w języku polskim, identyfikatory w kodzie po angielsku.

## Struktura repo
```
sources/        # jeden adapter na plik, wspólny interfejs fetch() -> list[RawEvent]
core/           # models.py, normalize.py, dedupe.py, geo.py, ics.py, digest.py, rollup_cinema.py
data/           # events.json, status.json, manual_events.yaml, venues.yaml, seen_ids.json
web/            # index.html, app.js, style.css, manifest.json, sw.js
tests/ + tests/fixtures/
docs/recon.md   # wynik etapu 0
.github/workflows/  # daily.yml, smoke.yml, keepalive.yml
```

## Model danych (`Event`, walidacja pydantic + JSON Schema w `data/schema.json`)
`id` (sha1 z znormalizowany_tytuł+start+miejsce), `title`, `start`, `end` (ISO 8601, strefa Europe/Warsaw), `all_day`, `venue`, `place`, `lat`, `lon`, `distance_km`, `category` (`scena|kino|biblioteka|edukacja|okolice|inne`), `url`, `ticket_url`, `price_text`, `times` (kino), `source`, `sources` (lista po dedupe), `first_seen`, `last_seen`, `status` (`active|cancelled`).
Przechowuj **tylko fakty** (tytuł, termin, miejsce, cena, linki). Nie kopiuj opisów, zdjęć ani plakatów (repo jest publiczne, a część źródeł to serwisy komercyjne). Zawsze linkuj do strony organizatora, a przy braku do źródła.

## Źródła (kolejność priorytetu przy deduplikacji: organizator > bilety > agregator)
1. **MDK Radomsko** (`mdkradomsko.pl`, WordPress + Pro Event Calendar, typ `pec-events`, sitemapa `pec-events-sitemap.xml`; bilety: `mdkradomsko.bilety24.pl`). Sprawdź najpierw `/wp-json/wp/v2/`, potem sitemapę i strony wydarzeń.
2. **radomsko.pl** – widżet „Kalendarz wydarzeń” (ładowany JS-em); znajdź endpoint JSON w ruchu sieciowym.
3. **Muzeum** (`muzeum.radomsko.pl`, WP), **MBP** (`mbp-radomsko.pl`, Joomla K2): RSS/REST; daty często w tekście, parser heurystyczny z oznaczeniem `confidence=low`.
4. **Agregatory z JSON-LD `Event`**: `radomsko.naszemiasto.pl/kalendarz-imprez`, `biletyna.pl` (Przedbórz i inne miasta), `radomskoogloszenia.pl/wydarzenia` (zawiera odległość w km), strony miast i miejsc na `ebilet.pl` (np. `/miasto/gomunice`, `/miejsce/klub-muzyczny-bogart-w-gomunicach`), `atrakcje.pl` (kalendarze miejscowości), serwis dożynek (JSON-LD). Jeden wspólny parser JSON-LD + cienkie nakładki per serwis.
5. **Okolice**: `kamiensk.pl` (kalendarz pod `/kalendarz/DD-MM-RRRR`), `mdk.przedborz.pl`, GOK Kłomnice (przez agregatory).
6. **Ręczne**: `data/manual_events.yaml` (Gomunice – `gomunice.pl` blokuje roboty, gminy bez kalendarza, plakaty). Źródło o najwyższym zaufaniu; nadpisuje automaty.
7. Radomszczańska (`radomszczanska.pl`), `radomsko.org`, `inforadomsko.pl`: tylko jako podpowiedzi do ręcznego uzupełniania (bez automatu, chyba że recon wykaże sensowny feed).

**Zakazy:** nie scrapuj Facebooka ani żadnego serwisu, którego `robots.txt` lub regulamin tego zabrania. Nie omijaj blokad. Przed włączeniem każdego adaptera zapisz w `docs/recon.md`: URL, wynik `robots.txt`, format danych, decyzja.

## Zasady scrapingu
User-Agent: `radomsko-events/1.0 (+URL repozytorium)`. Maks. ok. 1 żądanie/s na domenę, timeout 15 s, retry z backoffem (3×), ETag/If-Modified-Since gdzie się da, jeden przebieg dziennie, cache surowych odpowiedzi tylko w runie. `urllib.robotparser` przed każdą domeną.

## Normalizacja i deduplikacja
- Wszystkie daty do Europe/Warsaw (uwaga na DST; cron działa w UTC).
- Klucz dedupe: znormalizowany tytuł (bez diakrytyków, bez „bilety”, „koncert” itp.) + data + miejsce; dopasowanie rozmyte `rapidfuzz` (próg konfigurowalny, domyślnie 90) + ta sama data. Przy zbiegu: pola z organizatora wygrywają, agregator uzupełnia braki (cena, `ticket_url`).
- Geo: `data/venues.yaml` (nazwa → współrzędne), bez geokodowania w locie. Brak współrzędnych = wydarzenie trafia do `status.json` jako „do uzupełnienia”, nie na stronę.
- Filtr: `distance_km <= 30` lub miejscowość z `force_include: true` w `data/venues.yaml` (obecnie tylko Przedbórz). Kategoria `okolice` dla `distance_km > 0` poza Radomskiem.
- Kino: `rollup_cinema.py` łączy seanse tego samego filmu w jedną pozycję (start = pierwszy dzień, end = ostatni, `times` = godziny).
- Usuwanie: po dacie `end` (lub `start`, jeśli brak) wydarzenie znika z plików wynikowych.
- „Nowe”: `data/seen_ids.json` (id → first_seen). Nowe = id, którego nie było w poprzednim przebiegu. Trzymaj tylko id wydarzeń przyszłych (czyść razem z usuwaniem).

## Wyniki i publikacja
- `data/events.json` (źródło prawdy dla strony), `data/status.json` (per źródło: ostatni sukces, liczba wydarzeń, błąd), `public/events.ics` (VTIMEZONE Europe/Warsaw, stabilny `UID=<id>@radomsko-events`, `SEQUENCE` rośnie przy zmianie, `STATUS:CANCELLED` dla odwołanych przez 7 dni), `public/events.json`.
- Strona (`web/`): miesięczny kalendarz z kropkami kategorii, lista „Nadchodzące”, filtry kategorii, wyróżnienie „Nowe”, przyciski „Bilety/Szczegóły” i „Dodaj do kalendarza”, link do subskrypcji ICS (`webcal://`), stopka z godziną ostatniej aktualizacji i stanem źródeł. Baza wizualna: `web/legacy-dashboard.html` (poprzedni prototyp z danymi wpisanymi na stałe; przenieś układ i styl, dane czytaj z `events.json`). Dostępność: kontrast, focus, `prefers-color-scheme`, `prefers-reduced-motion`. PWA: manifest + prosty service worker (cache-first dla statyki, network-first dla JSON).
- Deploy przez `actions/deploy-pages`.

## Powiadomienia (ntfy)
- Temat w sekrecie `NTFY_TOPIC` (GitHub Secrets). **Nigdy nie commituj nazwy tematu** (repo publiczne). Opcjonalnie `NTFY_TOKEN`.
- Digest raz dziennie: tytuł „Radomsko: dziś X, w tygodniu Y”, treść: dziś (godzina, tytuł), najbliższe 7 dni (max 8 pozycji), „Nowe” (max 5, ze skrótem do strony). Przy braku zmian i braku wydarzeń dziś wysyłaj krótką wersję albo pomiń (konfiguruj w `config.yaml`).
- Osobny alert, gdy źródło nie działa >3 dni lub bezpiecznik zadziałał.

## Odporność
- Błąd jednego adaptera nie przerywa przebiegu.
- **Bezpiecznik:** gdy źródło zwraca 0 wydarzeń lub >50% mniej niż poprzednio, zachowaj poprzednie dane tego źródła, oznacz `stale`, wyślij alert.
- Workflow nie commituje, gdy dane się nie zmieniły (poza wpisem keepalive).
- Cron: `daily.yml` wieczorem, 16:41 UTC (18:41 CEST / 17:41 CET), plus przebiegi zapasowe 18:41 i 20:41 UTC. Digest na następny dzień jest wysyłany z zaplanowanym dostarczeniem ntfy na 7:00 (pole `delay`); przebieg do południa przygotowuje digest na bieżący dzień i wysyła go od razu (po 7:00) albo na 7:00. Job `gate` przepuszcza tylko pierwszy przebieg, który wyśle digest na dany dzień. Powód: GitHub opóźnia `schedule` (8–9.10.2026 o ok. 7 godzin przy cronie porannym). `workflow_dispatch` ręcznie. `keepalive.yml` co tydzień (unika wyłączenia zaplanowanych workflow po okresie bez aktywności w publicznym repo; zweryfikuj aktualne zasady GitHub).
- `smoke.yml` raz w tygodniu: lekkie zapytania na żywo do każdego źródła, sprawdzenie, że parser nadal zwraca dane.

## Testy i jakość
`pytest` z fixturami HTML/JSON zapisanymi w `tests/fixtures/<źródło>/` (parsery bez sieci), testy dedupe/rollup kina/DST/usuwania/„nowych”, test zgodności `events.json` ze schematem, generowanie ICS walidowane parserem `icalendar`. `ruff` w CI. Pokrycie krytycznych modułów (`dedupe`, `ics`, `digest`) wysokie.

## Sekrety i prywatność
Brak kluczy w repo. Sekrety: `NTFY_TOPIC`, opcjonalnie `NTFY_TOKEN`. Brak danych osobowych w danych wydarzeń (nie zapisuj nazwisk prywatnych osób, numerów telefonów z ogłoszeń).

## Etapy pracy (zatrzymaj się po każdym i pokaż wynik)
0. **Rozpoznanie** (`docs/recon.md`, fixtury): dla każdego źródła z listy sprawdź `robots.txt`, endpointy, format, JSON-LD, RSS, `wp-json`. Wylicz listę gmin w promieniu 30 km (z TERYT/Wikipedii, odległości programowo) i dla każdej znajdź stronę urzędu, GOK i bibliotekę oraz sprawdź je tak samo. Wynik: tabela źródło → decyzja (adapter / ręcznie / pominąć).
1. **Szkielet**: modele, schemat, config, adapter MDK, wspólny parser JSON-LD, `venues.yaml`, testy, prosty frontend na `events.json`.
2. **Pozostałe adaptery**, plik ręczny, dedupe, rollup kina, usuwanie po dacie, „nowe”.
3. **Automatyzacja**: ICS, digest ntfy, workflow dzienny, Pages.
4. **Hartowanie**: bezpiecznik, status źródeł, smoke test, README (instrukcja subskrypcji ICS i ntfy, dodawanie wydarzeń ręcznie, jak dodać nowy adapter).

## Kryteria akceptacji
Czysty `pytest` i `ruff`; `daily.yml` przechodzi na zielono i publikuje stronę; ICS importuje się w Outlooku i Google Calendar; digest dociera na telefon; wyłączenie jednego źródła nie psuje strony i generuje alert; po dacie wydarzenia znika z wyników; w README opisana procedura awaryjna.

## Styl pracy
Małe commity z opisowymi komunikatami. Nie dodawaj zależności bez uzasadnienia. Gdy źródło wymaga decyzji prawnej/etycznej (regulamin, blokada robotów), zatrzymaj się i zapytaj. Gdy coś nie działa lub nie da się zweryfikować, napisz to wprost w raporcie, bez zgadywania.
