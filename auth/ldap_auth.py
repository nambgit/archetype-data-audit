# auth/ldap_auth.py
import ssl
from ldap3 import Server, Connection, ALL, SIMPLE, Tls
from ldap3.utils.conv import escape_filter_chars
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

ALLOWED_GROUP_DN = "CN=IT Admins,OU=Groups,DC=archetype,DC=local"

def authenticate_user(username: str, password: str) -> bool:
    if not username or not password:
        return False

    # Chuẩn hóa UPN
    if '@' not in username:
        domain_parts = []
        for part in settings.AD_BASE_DN.split(','):
            if part.upper().startswith('DC='):
                domain_parts.append(part.split('=', 1)[1])
        domain = '.'.join(domain_parts)
        user_principal_name = f"{username}@{domain}"
    else:
        user_principal_name = username

    # === Cấu hình TLS với support cho Windows Server ===
    tls_config = None
    if settings.AD_USE_SSL:
        tls_config = Tls(
            validate=ssl.CERT_NONE,
            version=ssl.PROTOCOL_TLSv1_2,
            ciphers='ALL:@SECLEVEL=0'  # Cho phép cipher cũ hơn
        )

    # Quyết định dùng LDAPS hay STARTTLS
    use_ssl = settings.AD_USE_SSL and settings.AD_PORT == 636
    
    server = Server(
        settings.AD_SERVER,
        port=settings.AD_PORT,
        use_ssl=use_ssl,  # True nếu port 636, False nếu 389
        tls=tls_config if not use_ssl else None,  # Dùng cho STARTTLS
        get_info=ALL
    )

    try:
        conn = Connection(
            server,
            user=user_principal_name,
            password=password,
            authentication=SIMPLE,
            auto_bind=False  # Đổi thành False để handle STARTTLS
        )
        
        # Nếu dùng port 389, bật STARTTLS trước khi bind
        if settings.AD_PORT == 389 and settings.AD_USE_SSL:
            conn.open()
            conn.start_tls()
            conn.bind()
        else:
            conn.bind()
            
        if not conn.bound:
            logger.warning(f"LDAP bind failed for {username}")
            return False
            
        logger.debug(f"✅ LDAP bind successful for {username}")

        # Tìm user DN với filter an toàn
        safe_username = escape_filter_chars(username.split('@')[0])
        conn.search(
            search_base=settings.AD_BASE_DN,
            search_filter=f"(sAMAccountName={safe_username})",
            attributes=['distinguishedName']
        )
        
        if not conn.entries:
            logger.warning(f"User not found in AD: {username}")
            conn.unbind()
            return False

        user_dn = conn.entries[0].distinguishedName.value

        # Kiểm tra group membership
        conn.search(
            search_base=ALLOWED_GROUP_DN,
            search_filter="(objectClass=group)",
            attributes=['member']
        )
        
        if not conn.entries:
            logger.error(f"Allowed group not found: {ALLOWED_GROUP_DN}")
            conn.unbind()
            return False

        # Xử lý an toàn member attribute
        group_entry = conn.entries[0]
        group_members = (
            group_entry.member.values 
            if hasattr(group_entry, 'member') and group_entry.member 
            else []
        )
        
        is_member = user_dn in group_members
        conn.unbind()
        
        if is_member:
            logger.info(f"✅ Access granted for {username}")
            return True
        else:
            logger.warning(f"❌ Access denied: {username} not in IT Admins")
            return False

    except Exception as e:
        logger.warning(f"LDAP auth failed for {username}: {e}")
        return False