#!/bin/sh
set -eu

# Бот стартует после web (migrate выполняется там)
exec python -m bot.main
