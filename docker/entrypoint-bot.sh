#!/bin/sh
set -eu

# Бот стартует после web (migrate выполняется там); логи — storage/logs/bot.log через bot.main
exec python -m bot.main
