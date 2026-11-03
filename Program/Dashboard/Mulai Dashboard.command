#!/bin/zsh
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Jalankan python3 setup.py di folder Dashboard terlebih dahulu."
  read -k 1
  exit 1
fi
exec .venv/bin/python run.py
