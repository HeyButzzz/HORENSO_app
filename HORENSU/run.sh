#!/usr/bin/env bash
# One-file launcher for HORENSO.
# Installs dependencies (first run only, or whenever they're missing),
# seeds demo data (first run only), then starts the server.
#
# Usage:
#   bash run.sh            # normal start
#   bash run.sh --reset    # wipe the database and reseed demo data before starting

set -e

# Always run from this script's own folder, no matter where it's called from.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Locate a Python interpreter (works on Windows Git Bash/WSL and on Linux/Mac).
PYTHON_BIN=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [ -z "$PYTHON_BIN" ]; then
  echo "Python tidak ditemukan. Silakan install Python 3 terlebih dahulu (https://www.python.org/downloads/)."
  exit 1
fi

echo "==> Memeriksa dependencies..."
if ! "$PYTHON_BIN" -c "import flask, flask_sqlalchemy, flask_login, flask_wtf" >/dev/null 2>&1; then
  echo "==> Menginstal dependencies (sekali saja, mungkin perlu waktu)..."
  if ! "$PYTHON_BIN" -m pip install -r requirements.txt >/tmp/horensu_pip.log 2>&1; then
    echo "    Percobaan pertama gagal, mencoba dengan --user..."
    if ! "$PYTHON_BIN" -m pip install --user -r requirements.txt >/tmp/horensu_pip.log 2>&1; then
      echo "    Mencoba lagi dengan --break-system-packages..."
      "$PYTHON_BIN" -m pip install --user --break-system-packages -r requirements.txt || {
        echo "Gagal menginstal dependencies. Lihat detail di /tmp/horensu_pip.log atau jalankan manual:"
        echo "  $PYTHON_BIN -m pip install -r requirements.txt"
        exit 1
      }
    fi
  fi
fi

if [ "$1" == "--reset" ]; then
  echo "==> Mereset database & mengisi ulang data demo..."
  "$PYTHON_BIN" seed.py --reset
elif [ ! -f "instance/horensu.db" ]; then
  echo "==> Database belum ada, membuat & mengisi data demo..."
  "$PYTHON_BIN" seed.py
fi

echo ""
echo "==> Menjalankan HORENSO di http://10.10.20.19:8080"
echo "    Tekan CTRL+C untuk menghentikan server."
echo ""
"$PYTHON_BIN" run.py
