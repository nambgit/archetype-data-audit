# auth/ldap_auth.py
import ssl
from ldap3 import Server, Connection, ALL, NTLM, SIMPLE, Tls
from config.settings import settings
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Tên nhóm được phép (hoặc dùng DN nếu muốn chính xác tuyệt đối)
ALLOWED_GROUP_DN = "CN=IT Admins,OU=Groups,DC=archetype,DC=local"

def authenticate_user(username: str, password: str) -> bool:
    """
    Authenticate user against AD and check group membership.
    Only users in 'IT Admins' group are allowed.
    """
    if not username or not password:
        return False

    # Chuẩn hóa username thành UPN (user@domain)
    if '@' not in username:
        # Tạo domain từ AD_BASE_DN: DC=archetype,DC=local → archetype.local
        domain_parts = []
        for part in settings.AD_BASE_DN.split(','):
            if part.upper().startswith('DC='):
                domain_parts.append(part.split('=', 1)[1])
        domain = '.'.join(domain_parts)
        user_principal_name = f"{username}@{domain}"
    else:
        user_principal_name = username

    # Cấu hình server
    tls_config = None
    if settings.AD_USE_SSL and settings.LDAP_SKIP_CERT_VERIFY:
        tls_config = Tls(validate=ssl.CERT_NONE)
    elif settings.AD_USE_SSL:
        tls_config = Tls(validate=ssl.CERT_REQUIRED)

    server = Server(
        settings.AD_SERVER,
        port=settings.AD_PORT,
        use_ssl=settings.AD_USE_SSL,
        tls=tls_config,
        get_info=ALL
    )

    try:
        # Bước 1: Xác thực người dùng (bind)
        conn = Connection(
            server,
            user=user_principal_name,
            password=password,
            authentication=NTLM if not settings.AD_USE_SSL else SIMPLE,
            auto_bind=True
        )
        logger.debug(f"✅ LDAP bind successful for {username}")

        # Bước 2: Lấy distinguishedName của user
        conn.search(
            search_base=settings.AD_BASE_DN,
            search_filter=f"(sAMAccountName={username.split('@')[0]})",
            attributes=['distinguishedName']
        )
        if not conn.entries:
            logger.warning(f"User not found in AD: {username}")
            conn.unbind()
            return False

        user_dn = conn.entries[0].distinguishedName.value
        logger.debug(f"User DN: {user_dn}")

        # Bước 3: Kiểm tra xem user có trong nhóm IT Admins không
        conn.search(
            search_base=ALLOWED_GROUP_DN,
            search_filter="(objectClass=group)",
            attributes=['member']
        )
        if not conn.entries:
            logger.error(f"Allowed group not found: {ALLOWED_GROUP_DN}")
            conn.unbind()
            return False

        group_members = conn.entries[0].member.values if conn.entries[0].member else []
        if user_dn in group_members:
            logger.info(f"✅ Access granted for {username} (member of IT Admins)")
            conn.unbind()
            return True
        else:
            logger.warning(f"❌ Access denied: {username} is not in IT Admins group")
            conn.unbind()
            return False

    except Exception as e:
        logger.warning(f"LDAP auth failed for {username}: {e}")
        return False