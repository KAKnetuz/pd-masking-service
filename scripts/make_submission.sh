#!/bin/sh
# Архив для сдачи: только отслеживаемые git-файлы (без .git, .venv, __pycache__).
set -e
git archive --format=zip --output=pd-masking-service.zip HEAD
echo "Готово: pd-masking-service.zip"
