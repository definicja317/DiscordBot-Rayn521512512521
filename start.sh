#!/bin/bash
# Startowy skrypt dla Render Web Service

# Ustawienie portu, który Render automatycznie przekaże
export PORT=${PORT:-10000}

# Uruchomienie Twojego bota Discord (main.py)
python main.py