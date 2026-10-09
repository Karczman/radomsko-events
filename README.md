# Radomsko Events

Codziennie aktualizowany kalendarz wydarzeń kulturalnych, społecznych i edukacyjnych w Radomsku i do 30 km od niego (plus Przedbórz). Statyczna strona na GitHub Pages, dane w JSON, subskrypcja ICS i poranny digest przez ntfy. Bez serwera i bez bazy danych.

- Strona: https://karczman.github.io/radomsko-events/
- Kalendarz (ICS): `webcal://karczman.github.io/radomsko-events/events.ics`
- Specyfikacja projektu i decyzje: [CLAUDE.md](CLAUDE.md), wyniki rozpoznania źródeł: [docs/recon.md](docs/recon.md)

## Jak to działa

Raz dziennie, wieczorem (`daily.yml`, ok. 18:41 latem / 17:41 zimą), workflow pobiera wydarzenia z adapterów, normalizuje je (strefa Europe/Warsaw), łączy duplikaty między źródłami, zwija seanse kina, usuwa wydarzenia po dacie zakończenia, zapisuje wyniki w `data/` i wdraża stronę z `events.ics`. Na końcu planuje digest na następny dzień: ntfy dostarcza go o 7:00.

```
sources/      adaptery (jeden na źródło): fetch() -> list[RawEvent]
core/         modele, normalizacja, geo, dedupe, rollup kina, ICS, digest, bezpiecznik, smoke, build
data/         events.json, status.json, seen_ids.json, ics_state.json, manual_events.yaml, venues.yaml, source_cache/
web/          strona (HTML, CSS, vanilla JS), manifest PWA i service worker
tests/        pytest + fixtury w tests/fixtures/<źródło>/
.github/workflows/  daily, ci, smoke, keepalive
```

Przechowujemy tylko fakty (tytuł, termin, miejsce, cena, linki). Nie kopiujemy opisów, zdjęć ani plakatów i zawsze linkujemy do strony organizatora.

### Źródła

| Źródło | Typ |
|---|---|
| MDK Radomsko | REST WordPress (`pec-events`); terminy z `pec_date`, `pec_extra_dates` (repertuar kina) i cyklu dziennego |
| radomsko.pl | widżet kalendarza miejskiego (HTML) |
| Muzeum Regionalne, MBP | WP REST i RSS, daty z tekstu (`confidence=low`) |
| biletyna.pl, ebilet.pl | JSON-LD `Event` (tylko listingi dozwolone przez `robots.txt`) |
| Kamieńsk, MDK Przedbórz | HTML |
| `data/manual_events.yaml` | wpisy ręczne, najwyższe zaufanie |

Pominięte: naszemiasto.pl (HTTP 403 dla robotów), radomskoogloszenia.pl (regulamin XIII.2), Facebook. Szczegóły i uzasadnienia w [docs/recon.md](docs/recon.md).

Scraping jest grzeczny: User-Agent `radomsko-events/1.0`, ok. 1 żądanie/s na domenę, `robots.txt` sprawdzany przed każdą domeną, timeout 15 s, 3 próby z odczekaniem, jeden przebieg dziennie.

## Subskrypcja kalendarza (ICS)

Adres: `https://karczman.github.io/radomsko-events/events.ics` (na stronie jest też przycisk „Kopiuj adres”). Kalendarz odświeża się co kilka godzin po stronie aplikacji kalendarza, nie natychmiast.

- **iPhone / Mac (Kalendarz):** Plik → Nowa subskrypcja kalendarza (Mac) albo Ustawienia → Kalendarz → Konta → Dodaj konto → Inne → Dodaj kalendarz subskrybowany (iPhone). Wklej adres.
- **Google Calendar (www):** Inne kalendarze (+) → Z adresu URL, wklej adres. W aplikacji mobilnej subskrypcje dodaje się tylko w wersji przeglądarkowej.
- **Outlook:** Dodaj kalendarz → Subskrybuj z internetu, wklej adres.

Wydarzenia mają stabilny `UID`, a `SEQUENCE` rośnie przy zmianie (aplikacje aktualizują wpis, a nie dublują go). Odwołane wydarzenia zostają jako „Odwołane” przez 7 dni.

## Powiadomienia ntfy

1. Zainstaluj aplikację **ntfy** (App Store / Google Play).
2. Wymyśl długi, losowy temat (np. `radomsko-` + 20 losowych znaków). Temat jest jedynym zabezpieczeniem kanału, więc nie ma go w repo.
3. W aplikacji subskrybuj ten temat (serwer `ntfy.sh`).
4. W repo dodaj sekret o tej samej wartości: Settings → Secrets and variables → Actions → New repository secret, nazwa `NTFY_TOPIC` (albo `gh secret set NTFY_TOPIC`). Opcjonalnie `NTFY_TOKEN`, jeśli używasz chronionego tematu.

Digest raz dziennie: „Radomsko: dziś X, w tygodniu Y”, a w treści: dziś (godzina i tytuł), najbliższe 7 dni (max 8), nowe (max 5). Gdy nic dziś i nic nowego, wysyłana jest krótka wersja (3 najbliższe wydarzenia) albo nic, zależnie od `digest.when_empty` w `config.yaml` (`short` lub `skip`).

Osobny alert przychodzi, gdy źródło nie działa dłużej niż 3 dni, gdy zadziałał bezpiecznik (patrz niżej) albo gdy tygodniowy test dymny wykryje problem.

Test ręczny bez wysyłania: `python -m core.digest --dry-run`.

## Dodawanie wydarzeń ręcznie

Edytuj [data/manual_events.yaml](data/manual_events.yaml) (można prosto z przeglądarki na GitHubie) i zrób commit. Wpis ręczny ma najwyższy priorytet: nadpisuje dane z automatów dla tego samego wydarzenia.

```yaml
events:
  - title: "Dożynki gminne"
    start: "2026-09-05 14:00"      # RRRR-MM-DD GG:MM albo samo RRRR-MM-DD (wydarzenie całodniowe)
    end: "2026-09-05 20:00"        # opcjonalnie
    venue: "Stadion w Gomunicach"  # opcjonalnie
    place: "Gomunice"              # wymagane, musi być w data/venues.yaml
    category: okolice              # scena | kino | biblioteka | edukacja | okolice | inne
    url: "https://gomunice.pl/"
```

Wymagane pola: `title`, `start`, `place`. Wydarzenie poza zasięgiem 30 km albo w miejscowości spoza `data/venues.yaml` nie trafi na stronę, tylko do `data/status.json` w polu `to_complete` (dopisz miejscowość do `venues.yaml`). Zmiana pojawi się na stronie po najbliższym przebiegu `daily` albo od razu po ręcznym uruchomieniu (Actions → daily → Run workflow).

## Dodawanie nowego adaptera

1. **Rozpoznanie:** sprawdź `robots.txt`, regulamin i format danych (REST, RSS, JSON-LD, HTML). Wpisz wynik do [docs/recon.md](docs/recon.md). Nie scrapuj serwisów, które tego zabraniają, i nie omijaj blokad.
2. **Fixtura:** zapisz 1–2 odpowiedzi w `tests/fixtures/<źródło>/` (same fakty, bez danych osobowych).
3. **Adapter:** plik `sources/<źródło>.py` z klasą dziedziczącą po `sources.base.Source` (`name`, `fetch(fetcher) -> list[RawEvent]`). Rozbij kod na czystą funkcję parsującą (testowalną bez sieci) i cienkie `fetch`. Dla serwisów z JSON-LD użyj gotowego `sources.jsonld` i `JsonLdListingSource`.
4. **Rejestracja:** dopisz źródło do `build_sources()` w `core/build.py`, do `sources:` w `config.yaml` i do priorytetów w `core/dedupe.py` (`SOURCE_PRIORITY`: organizator przed biletami przed agregatorem).
5. **Smoke:** dodaj sprawdzenie do `CHECKS` w `core/smoke.py` (test pilnuje, że każde włączone źródło je ma).
6. **Testy:** parser na fixturach (`tests/test_*.py`), potem `ruff check .` i `pytest`.
7. **Miejsca:** jeśli wydarzenia są w nowej miejscowości, dopisz obiekt do `venues:` w `data/venues.yaml` (współrzędne obiektu albo siedziby gminy).

## Rozwój lokalny

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/pytest -q
.venv/bin/python -m core.build          # pobiera dane na żywo, zapisuje data/ i public/
.venv/bin/python -m core.smoke          # test dymny źródeł
.venv/bin/python -m http.server 8765 --directory public   # podgląd strony
```

`core.build` robi prawdziwe żądania (ok. 70 w sumie, w tym 45 do Kamieńska), więc nie uruchamiaj go w pętli.

## Bezpiecznik i status źródeł

Gdy źródło zwraca 0 wydarzeń lub ponad 50% mniej różnych tytułów niż poprzednio (liczą się tytuły, nie terminy, bo seanse kina wygasają codziennie; tylko gdy poprzednio było ich co najmniej 5), albo rzuca wyjątek, build:

- zachowuje ostatnie dobre dane tego źródła z `data/source_cache/` (bez wydarzeń z przeszłości),
- oznacza je w `data/status.json` jako `stale` (z powodem i datą od kiedy),
- wysyła alert ntfy przy najbliższym digeście,
- pokazuje problem w stopce strony („Źródła danych”).

Gdy źródło wróci do normy, oznaczenie znika samo. Awaria jednego źródła nie przerywa przebiegu i nie psuje strony.

## Procedura awaryjna

**Workflow `daily` jest czerwony albo strona się nie aktualizuje**
1. Repo → Actions → `daily` → otwórz nieudany przebieg i jego log (który job: build, deploy czy notify).
2. Chwilowa usterka GitHuba (np. HTTP 500 przy uruchamianiu): uruchom ponownie (Re-run albo Run workflow). Przy pierwszym wdrożeniu zdarzyło się to raz i kolejny przebieg przeszedł bez zmian.
3. Build się wywraca na kodzie: napraw adapter albo wyłącz źródło (`enabled: false` w `config.yaml`; uwaga: wydarzenia tego źródła znikną ze strony, dopisz ważne ręcznie). Zasady są w sekcji „Dodawanie nowego adaptera”.
4. Deploy: sprawdź Settings → Pages (Source musi być „GitHub Actions”) i Settings → Environments → github-pages.

**Jedno źródło nie działa (alert „problem ze źródłem”)**
1. Strona pokazuje w stopce, które źródło i od kiedy. Przez ten czas widać jego ostatnie dobre dane.
2. Uruchom lokalnie `python -m core.smoke`, żeby zobaczyć, co się zmieniło (adres, struktura HTML, blokada).
3. Zaktualizuj fixturę i parser, albo dopisz wydarzenia ręcznie do `data/manual_events.yaml`.

**Na stronie pojawiły się złe dane**
1. Przywróć poprzednie dane: `git log -- data/events.json`, potem `git checkout <sha> -- data && git commit -m "Przywrócenie danych"` i push.
2. Znajdź przyczynę (źródło, `dedupe`), bo następny przebieg nadpisze dane, jeśli problem nadal istnieje. W razie potrzeby wyłącz źródło w `config.yaml`.

**Powiadomienia nie przychodzą**
1. Sprawdź log joba `notify` (czy jest „wysłano: …”). Brak sekretu `NTFY_TOPIC` kończy się komunikatem o braku tematu i niczego nie wysyła.
2. Sprawdź, czy telefon jest zapisany na ten sam temat.
3. Podejrzenie wycieku tematu: ustaw nową wartość `NTFY_TOPIC` i zapisz się na nowy temat w aplikacji.

**Digest przyszedł późno albo wcale**
GitHub opóźnia zaplanowane przebiegi (8–9.10.2026 o ok. 7 godzin) i może je pominąć. Dlatego dane pobieramy wieczorem (16:41 UTC, zapasy 18:41 i 20:41 UTC), a digest na następny dzień ntfy dostarcza o 7:00 (zaplanowana wysyłka). Przebieg spóźniony do rana wysyła digest od razu. Job `gate` przepuszcza tylko pierwszy przebieg, który wyśle digest na dany dzień. Jeśli nic nie przyszło: Actions → `daily` (czy był przebieg `schedule` i w logu joba `notify` „wysłano: … (dostarczenie: …)”?), w razie potrzeby Run workflow ręcznie (ręczny przebieg działa zawsze).

**Zaplanowane workflow przestały się uruchamiać**
GitHub wyłącza je w publicznym repo po 60 dniach bez aktywności. `keepalive.yml` robi własny commit (`data/keepalive.txt`), gdy ostatni commit jest starszy niż 45 dni. Dokumentacja GitHuba nie precyzuje, co dokładnie liczy się jako aktywność, więc jeśli mimo to workflow się wyłączy: Actions → wybierz workflow → Enable workflow (albo `gh workflow enable daily.yml`).

**GitHub Pages niedostępny**
Dane są też w repo (`data/events.json`). Lokalnie: `python -m core.build` i `python -m http.server --directory public`, albo odczytaj `data/events.json`. Subskrypcje ICS po wznowieniu Pages działają bez zmian (adres i `UID` się nie zmieniają).

## Zależności i aktualizacje

Wersje wszystkich pakietów (także pośrednich) są zablokowane z sumami kontrolnymi w `requirements.txt` (produkcja) i `requirements-dev.txt` (testy, ograniczony do tych samych wersji). Workflowy instalują je z `--require-hashes` i sprawdzają spójność (`pip check`), a akcje GitHuba są przypięte do SHA.

- Zmiana zależności w `pyproject.toml` albo aktualizacja wersji: `scripts/update-locks.sh` (z `--upgrade` dla najnowszych zgodnych wersji), potem testy.
- Dependabot co tydzień otwiera jeden zbiorczy PR dla Pythona i jeden dla akcji. Scalaj tylko po zielonym CI. Pakiety zależne od siebie (np. `pydantic` przypina dokładną wersję `pydantic-core`) muszą zmieniać się razem; PR z jednym z nich zatrzyma `pip check`.
- W repo działają alerty Dependabota, ochrona `main` (bez force-pusha i usuwania), wyłącznie akcje GitHuba przypięte do SHA, skanowanie sekretów z blokadą pushu.

## Kontrola jakości

- `ci.yml`: `ruff check .` i `pytest` przy każdym pushu poza zmianami w `data/` i przy pull requestach.
- `smoke.yml`: raz w tygodniu (środa 06:30 UTC) lekkie zapytania na żywo do każdego źródła. Przy problemie przebieg jest czerwony i przychodzi alert ntfy.
- `daily.yml` nie commituje, gdy dane się nie zmieniły.

## Sekrety i prywatność

Strona nie łączy się z żadnym obcym serwerem (czcionka Bricolage Grotesque na licencji SIL OFL jest hostowana razem ze stroną), nie używa ciasteczek ani analityki. Zgłoszenia testerów trafiają do publicznych GitHub Issues (formularze ostrzegają przed podawaniem danych osobowych; do zgłoszenia potrzebne jest konto GitHub).

W repo nie ma kluczy. Sekrety: `NTFY_TOPIC` i opcjonalnie `NTFY_TOKEN` (GitHub Secrets). Dane wydarzeń nie zawierają danych osobowych (nazwisk prywatnych osób ani numerów telefonów z ogłoszeń).
