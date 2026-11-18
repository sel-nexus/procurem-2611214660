"""Protect passwords and opaque session credentials."""
import hashlib
import secrets
import bcrypt

def hash_password(password: str) -> str:
    """Hash a password with a unique salt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against its stored hash."""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False

def new_token() -> str:
    """Generate an unpredictable session credential."""
    return secrets.token_urlsafe(32)

def token_hash(token: str) -> str:
    """Derive the stored digest of a session credential."""
    return hashlib.sha256(token.encode()).hexdigest()
