# Structure
archetype-data-audit/
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
│
├── config/
│   └── settings.py          ← Config from .env
│
├── db/
│   ├── __init__.py
│   ├── connection.py        ← Connection PostgreSQL
│   └── schema.sql           ← Schema PostgreSQL
│
├── scanner/
│   ├── __init__.py
│   ├── file_scanner.py      ← Scan File Server
│   └── sharepoint_scanner.py← Scan SharePoint
│
├── archive/
│   └── s3_archiver.py       ← S3 storage
│
├── auth/
│   └── graph_auth.py        ← Microsoft Graph Auth
│
├── web/
│   ├── __init__.py
│   ├── app.py               ← Flask Web UI
│   └── templates/index.html
│
├── logs/                    ← Logs folder
└── main.py                  ← Entry point

# Deployment Guide
STEP 1: Setup
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your values

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

