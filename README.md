# Deployment Guide
STEP 1: Setup
pip install -r requirements.txt
cp .env.example .env
Edit .env with your values

STEP 2: Initialize Database:
bash
python main.py --init-db

STEP 3: Scan Files:
bash
python main.py --scan-fs # Scan File Server

python main.py --scan-sp # Scan Share Point

STEP 4: Start Web UI:
bash
python -m web.app
# Access: http://localhost:5000

