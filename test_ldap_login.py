# test_ldap_login.py
import os
import sys

# Thêm thư mục gốc vào Python path để import được config và auth
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth.ldap_auth import authenticate_user

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python test_ldap_login.py <username> <password>")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]

    print(f"Testing LDAP login for: {username}")
    if authenticate_user(username, password):
        print("✅ SUCCESS: Authentication and group check passed!")
    else:
        print("❌ FAILED: Invalid credentials or not in 'IT Admins' group.")