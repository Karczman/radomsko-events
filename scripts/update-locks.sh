#!/usr/bin/env bash
# Regeneruje pliki blokad zależności (wersje + sumy kontrolne) w spójny sposób:
# requirements.txt z pyproject.toml, a requirements-dev.txt ograniczony do tych samych wersji (-c),
# więc produkcja i CI zawsze używają identycznych pakietów. Wymaga `uv`.
#   scripts/update-locks.sh            # tylko dopasowanie do pyproject.toml
#   scripts/update-locks.sh --upgrade  # dodatkowo najnowsze zgodne wersje
set -euo pipefail
cd "$(dirname "$0")/.."
common=(--generate-hashes --python-version 3.12 --universal -q)
uv pip compile pyproject.toml "${common[@]}" "$@" -o requirements.txt
uv pip compile pyproject.toml --extra dev -c requirements.txt "${common[@]}" "$@" -o requirements-dev.txt
echo "Zaktualizowano requirements.txt i requirements-dev.txt. Uruchom testy przed commitem."
