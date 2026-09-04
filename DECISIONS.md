# DECISIONS - participation-architecture

<!-- catalog-read --> repo nie miało DECISIONS.md; decyzje architektoniczne żyły w docstringach silnika, dzienniku wskaźnika DFI (`pa/dziennik-wskaznika-dfi.md`) i rejestrze pomiarów. Ten plik zbiera wybory dotyczące KODU; dziennik zostaje właścicielem wiedzy o INSTRUMENCIE.

## 2026-09-04 - Cross-Layer Closure Review: obserwacja zamrożona, źródła z pokwitaniem, rejestr pomiarów

**Kontekst.** Recenzent (`AIE - Integrity Research`, /t/30604, 03.09) uznał, że naprawy z 28.08 domknęły cztery bramki na powierzchni, a te same usterki wróciły warstwę niżej. Sześć wymaganych napraw, z zastrzeżeniem, że kolejna lokalna łatka nie zamknie recenzji.

**Wybory (choice):**
- **Etap decyzji = zamrożona obserwacja, cykl to metadane.** Odrzucone: dotychczasowe scalanie etapów w jeden obiekt z „najdłuższą treścią" i kategorią z etapu, który ją znał - to przeciek w przyszłość przez mutację celu (obiekt o t1 niósł treść z t2). Zliczanie volume/burstiness po cyklach robi `compute_per_event._decision_representatives` na niezmiennych obiektach. Cena: `lifecycle_id` liczony z zaobserwowanych etapów zmienia się, gdy pierwszy etap wypadnie poza okno skanu (manifest niesie `lifecycle_stage_ids` do porównań).
- **Fail-closed przez werdykt, nie przez nazwę.** Odrzucone: samo nazwanie fallbacku (`concurrency_source=voted_only`) jako wystarczająca przejrzystość. Każde źródło zwraca `SourceReceipt` (7 stanów), a `fatigue_config.yaml#eligibility` (logic_as_data) rozstrzyga `PRIMARY_ELIGIBLE` / `NOT_ELIGIBLE_FOR_PRIMARY_ANALYSIS`. Liczba nadal się liczy i pokazuje - z werdyktem. TRUNCATED oceniane względem okna kontekstu po `oldest_cast_at`, bo aktywny delegat (P02, 408 głosów) ma kompletne 30 dni mimo obcięcia strony.
- **Taksonomia DAO (arbdata) jest źródłem wymaganym.** Znalezione na produkcji po pierwszym deployu: endpoint odpowiadał 403, `load()` zwracał 0 po cichu, novelty spadało na listę słów u wszystkich przy czystym werdykcie. Udany odczyt zapisuje `data/cache/arbdata-registry.json`; kopia wchodzi jako PARTIAL z datą (taksonomia przeszłych propozycji nie zmienia się), brak kopii = ERROR = NOT_ELIGIBLE.
- **GET czyta, POST rejestruje.** Odrzucone: zapis przy każdym GET (odświeżenie przeglądarki tworzyło wiersz). `measurement_id` = skrót całego manifestu, indeks UNIQUE (alembic 003); POST zwraca `persisted: true|false`. `pa/analiza/prep-dataset.py` woła POST, bo liczba w zbiorze analizy jest pomiarem.
- **Instrument bez wag domyślnych.** `InstrumentInvalid` przy braku pliku, złym YAML, brakującym kluczu, wagach ≠ 1,0 lub wartości logicznej zamiast liczby; endpoint 503 `INSTRUMENT_INVALID`. Odrzucone: ostrzeżenie i liczenie dalej (stan sprzed 04.09).

**Cross-module.** Klienci źródeł (`snapshot_client`, `tally_client`, `governor_client`, `arbdata_client`) importują `SourceReceipt` z `fatigue_engine` - kierunek „klient zna format pokwitania silnika". Alternatywa (osobny moduł `receipts.py`) odłożona: jeden importer, brak cyklu (`fatigue_engine` nie importuje klientów).

**Cross-module (dysertacja).** Zmiana instrumentu wymaga wpisu w `pa/dziennik-wskaznika-dfi.md` (D24) i `pa/rejestr-pomiarow.yaml` (v-2026-09-04) - hook Stop pilnuje. Wartości per-event sprzed 04.09 dla delegatów z dwuetapowymi decyzjami albo z kategoriami nie są porównywalne z v-2026-09-04.

**Bug from ignorance.** Cel siedział we własnej historii w `_novelty_per_event`: pierwszy głos delegata w kategorii dawał 1 - 1/1 = 0,0. Sufit składnika był osiągalny wyłącznie przez zapasowe dopasowanie po słowach. Wyszło przy rozdzielaniu etapów.

**Trwałość rejestru (D4=A).** Baza SQLite produkcji żyła w obrazie kontenera; `pa/deploy-arbitrum.sh` przenosi ją na wolumen `/opt/arbitrum-data` przy następnym deployu, kopiując bieżącą bazę z kontenera. Do tego czasu `pa/rejestr-pomiarow.yaml` jest kopią zapasową wpisów.

Testy: 170 (było 123). Commity: `ecbc851`, `036d8a1`, `ca6aeef`.
