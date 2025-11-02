"""
Main entry point for the Data Audit System.
Usage:
  python main.py --init-db    # Initialize database
  python main.py --scan-fs       # Run file server scanner
  python main.py --scan-sp      # Scan SharePoint
  python main.py --scan-all     # Scan both: FileServer and SharePoint
"""

import argparse
from db.connection import init_db
from scanner.file_scanner import scan_file_server
from scanner.sharepoint_scanner import scan_sharepoint

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ArcheType Data Audit System")
    parser.add_argument("--init-db", action="store_true", help="Initialize PostgreSQL database")
    parser.add_argument("--scan-fs", action="store_true", help="Scan file server and update audit records")
    parser.add_argument("--scan-sp", action="store_true", help="Scan SharePoint")
    parser.add_argument("--scan-all", action="store_true", help="Scan both FileServer and SharePoint")
    
    args = parser.parse_args()
    
    if args.init_db:
        init_db()
    elif args.scan_fs:
        scan_file_server()
    elif args.scan_sp:
        scan_sharepoint()
    elif args.scan_all:
        scan_file_server()
        scan_sharepoint()
    else:
        parser.print_help()