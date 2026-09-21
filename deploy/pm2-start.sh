#!/usr/bin/env bash
set -euo pipefail
cd /home/root/projects/kareem
mkdir -p logs
source venv/bin/activate
pip install -r requirements.txt
flask --app wsgi db upgrade
python scripts/seed.py
pm2 startOrRestart ecosystem.config.cjs --update-env
pm2 save
pm2 status kareem-market
