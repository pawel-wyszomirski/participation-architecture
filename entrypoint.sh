#!/bin/sh
# Z14: start kontenera nie zasilal bazy.
#
# `CMD ["uvicorn", ...]` uruchamial sam serwer. Interfejs wstawal na pustym
# zbiorze, odpowiadal poprawnie i nie mial czego triazowac - a healthcheck
# zwracal "ok". Trzy usterki skladaly sie na obraz uslugi gotowej do pracy,
# ktora nie moze wykonac swojego zadania.
#
# Zasilenie jest DOMYSLNE, bo triaz bez korpusu jest bezuzyteczny. Wylacza sie
# je swiadomie przez INGEST_ON_START=0 - na przyklad gdy dane wgrywa osobny
# proces albo gdy kontener ma tylko odczytywac wspolna baze.
set -e

if [ "${INGEST_ON_START:-1}" = "1" ]; then
    echo "📥 Zasilanie korpusu przed startem (INGEST_ON_START=1)..."
    if python -m app.services.snapshot_client; then
        echo "✅ Korpus zasilony."
    else
        # Awaria zasilenia NIE zatrzymuje serwera: usluga ma wstac i POWIEDZIEC
        # przez /health, ze nie jest gotowa. Kontener, ktory umiera po cichu,
        # daje mniej informacji niz kontener raportujacy powod.
        echo "❌ Zasilanie korpusu nie powiodlo sie - /health zglosi not_ready." >&2
    fi
else
    echo "⏭  Zasilanie pominiete (INGEST_ON_START=0)."
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
