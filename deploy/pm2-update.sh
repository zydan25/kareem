#!/usr/bin/env bash
set -euo pipefail
cd /home/root/projects/kareem
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
flask --app wsgi db upgrade
python scripts/seed.py
pm2 restart kareem-market --update-env
pm2 save
