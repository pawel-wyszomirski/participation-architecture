#!/usr/bin/env bash
# Kopia pomiarow POZA wolumen kontenera (P8, plan domkniecia z 2026-09-11, sekcja 9).
#
# Wolumen chroni przed przebudowa obrazu, ale nie przed `docker compose down -v`, awaria
# dysku ani pomylka operatora. Ta kopia idzie do katalogu na hoscie, ktory nie jest
# zarzadzany przez Dockera.
#
# Co kopiujemy: baze pomiarow ORAZ eksport manifestow append-only. Manifest wystarcza do
# odtworzenia pelnego wyniku bez sieci (`FatigueEngine.replay`), wiec kopia manifestow jest
# wazniejsza od kopii bazy - baza jest wygoda dostepu, manifest jest dowodem.
#
# Uzycie:  scripts/kopia-pomiarow.sh [katalog-docelowy] [nazwa-kontenera]
set -euo pipefail

CEL="${1:-/opt/pa-kopie}"
KONTENER="${2:-pa-api-badawcze}"
STEMPEL="$(date -u +%Y-%m-%dT%H%M%SZ)"
DOCELOWY="${CEL}/${STEMPEL}"

mkdir -p "${DOCELOWY}"

if docker ps --format '{{.Names}}' | grep -qx "${KONTENER}"; then
    # `docker cp` z dzialajacego kontenera moze zlapac baze w trakcie zapisu, dlatego
    # SQLite kopiujemy jego wlasnym mechanizmem - `.backup` jest spojny przy otwartym pliku.
    docker exec "${KONTENER}" sh -c \
        'command -v sqlite3 >/dev/null && sqlite3 /app/data/participation.db ".backup /app/data/kopia-chwilowa.db"' \
        || echo "! sqlite3 w kontenerze niedostepny - kopiuje plik na zywo (moze byc niespojna)"
    docker cp "${KONTENER}:/app/data/kopia-chwilowa.db" "${DOCELOWY}/participation.db" 2>/dev/null \
        || docker cp "${KONTENER}:/app/data/participation.db" "${DOCELOWY}/participation.db"
    docker exec "${KONTENER}" rm -f /app/data/kopia-chwilowa.db || true
    docker cp "${KONTENER}:/app/data/manifests" "${DOCELOWY}/manifests" 2>/dev/null \
        || echo "! brak katalogu manifests w kontenerze"
else
    echo "! kontener ${KONTENER} nie dziala - kopiuje z drzewa roboczego"
    cp -a data/participation.db "${DOCELOWY}/" 2>/dev/null || true
    cp -a data/manifests "${DOCELOWY}/manifests" 2>/dev/null || true
fi

# Liczba wierszy manifestow to jedyny licznik, ktory mowi, ILE pomiarow uratowano.
# Bez niej "kopia zrobiona" znaczy tylko, ze skrypt sie nie wywrocil.
LICZBA=0
if [ -d "${DOCELOWY}/manifests" ]; then
    LICZBA=$(find "${DOCELOWY}/manifests" -name 'pomiary-*.jsonl' -exec cat {} + 2>/dev/null | grep -c . || true)
fi
echo "kopia: ${DOCELOWY}"
echo "manifestow w kopii: ${LICZBA}"
[ "${LICZBA}" -gt 0 ] || echo "! UWAGA: zero manifestow - sprawdz, czy rejestracja ich zapisuje"
