"""
Security utilities for Nova Hub

Provides authentication and authorization for both Service API (OAuth2)
and Management API (session-based JWT).
"""

import time
from datetime import timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.core.config import get_config
from backend.core.database import get_db


# OAuth2 scheme for Service API
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/service/api/v1/auth/token")


def get_jwt_settings():
    """Get JWT settings from config"""
    config = get_config()
    return {
        "secret_key": config.security.jwt_secret,
        "algorithm": "HS256",
        "access_token_expire_minutes": config.security.jwt_expiry_hours * 60,
    }


_INSECURE_JWT_SECRETS = {
    "change-me-in-production",
    "secret",
    "changeme",
    "password",
    "",
}
_JWT_SECRET_MIN_LENGTH = 32


def validate_jwt_secret(secret: str) -> None:
    """
    Validate JWT secret strength.  Call at startup; raises ValueError if weak.
    """
    if secret.lower() in _INSECURE_JWT_SECRETS:
        raise ValueError(
            "JWT secret is set to an insecure default value. "
            "Generate a strong secret with: python generate_jwt_secret.py"
        )
    if len(secret) < _JWT_SECRET_MIN_LENGTH:
        raise ValueError(
            f"JWT secret must be at least {_JWT_SECRET_MIN_LENGTH} characters. "
            f"Current length: {len(secret)}. "
            "Generate a strong secret with: python generate_jwt_secret.py"
        )


def validate_password(password: str) -> None:
    """
    Enforce password policy.  Raises ValueError with a descriptive message if policy fails.
    Policy: minimum length from config, at least one uppercase, one lowercase, one digit.
    """
    config = get_config()
    min_len = config.security.min_password_length
    if len(password) < min_len:
        raise ValueError(f"Password must be at least {min_len} characters long.")
    if not any(c.isupper() for c in password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must contain at least one digit.")
    # bcrypt reads at most 72 bytes and stops at a NUL; newer versions refuse both.
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes.")
    if "\x00" in password:
        raise ValueError("Password must not contain a NUL character.")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token

    Args:
        data: Claims to include in the token
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string
    """
    settings = get_jwt_settings()
    to_encode = data.copy()

    if expires_delta:
        expire = utcnow() + expires_delta
    else:
        expire = utcnow() + timedelta(minutes=settings["access_token_expire_minutes"])

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings["secret_key"], algorithm=settings["algorithm"])
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """
    Verify and decode a JWT token

    Args:
        token: JWT token string

    Returns:
        Decoded token payload or None if invalid
    """
    settings = get_jwt_settings()
    try:
        payload = jwt.decode(token, settings["secret_key"], algorithms=[settings["algorithm"]])
        return payload
    except JWTError:
        return None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash using bcrypt.

    False, never an exception, for input bcrypt refuses (newer versions raise
    on more than 72 bytes) or a stored value that isn't a bcrypt hash: either
    way it is a failed sign-in, and must be counted as one.
    """
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# Checked against when there is no account to check, so a miss takes as long
# as a wrong password and doesn't say which names exist.
_DUMMY_HASH = bcrypt.hashpw(b"nova-hub timing pad", bcrypt.gensalt()).decode("utf-8")


def burn_password_check(plain_password: str) -> None:
    """Spend a bcrypt check's time on nothing."""
    verify_password(plain_password, _DUMMY_HASH)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# Alias for consistency with naming conventions
get_password_hash = hash_password


# --- Service API Authentication (OAuth2) ---

async def get_current_client(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """
    Get the current authenticated client from OAuth2 token

    For use in Service API endpoints.

    Raises:
        HTTPException: If token is invalid or client not found
    """
    from backend.models.database import Client

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = verify_token(token)
    if payload is None:
        raise credentials_exception

    # Enforce token type to prevent management tokens from being used here
    if payload.get("type") != "service":
        raise credentials_exception

    client_id: str = payload.get("sub")
    if client_id is None:
        raise credentials_exception

    client = db.query(Client).filter(Client.client_id == client_id).first()
    if client is None:
        raise credentials_exception

    from backend.services.client_secrets import token_revoked

    if token_revoked(client, payload.get("iat")):
        raise credentials_exception

    if not client.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client is inactive"
        )

    return client


def verify_client_credentials(client_id: str, client_secret: str, db: Session):
    """
    Verify OAuth2 client credentials

    Args:
        client_id: Client identifier
        client_secret: Client secret (plaintext)
        db: Database session

    Returns:
        Client instance if valid, None otherwise
    """
    from backend.models.database import Client

    client = db.query(Client).filter(Client.client_id == client_id).first()

    if not client or not client.is_active:
        burn_password_check(client_secret)
        return None

    from backend.services.client_secrets import matches

    if not matches(client, client_secret):
        return None

    return client


# --- Management API Authentication (Session JWT) ---

COOKIE_NAME = "nova_hub_session"


async def get_current_user(request: Request, db: Session = Depends(get_db)):
    """
    Get the current authenticated user from session cookie

    For use in Management API endpoints.

    Raises:
        HTTPException: If not authenticated or user not found
    """
    from backend.models.database import SysopUser

    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    payload = verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session"
        )

    # Enforce token type to prevent service tokens from being used here
    if payload.get("type") != "management":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session"
        )

    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session"
        )

    user = db.query(SysopUser).filter(SysopUser.username == username).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive"
        )

    return user


async def get_current_user_optional(request: Request, db: Session = Depends(get_db)):
    """
    Get current user if authenticated, None otherwise

    For endpoints that work both authenticated and unauthenticated.
    """
    from backend.models.database import SysopUser

    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    payload = verify_token(token)
    if payload is None:
        return None

    # A service token is signed with the same key: only a session token counts here.
    if payload.get("type") != "management":
        return None

    username: str = payload.get("sub")
    if username is None:
        return None

    user = db.query(SysopUser).filter(SysopUser.username == username).first()
    if user is None or not user.is_active:
        return None

    return user


def create_session_response(response, username: str):
    """
    Add session cookie to response

    Args:
        response: FastAPI response object
        username: Username to store in session
    """
    config = get_config()
    token = create_access_token(data={"sub": username, "type": "management"})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=config.security.cookie_secure,
        samesite="lax",
        max_age=config.security.jwt_expiry_hours * 3600
    )
    return response


def clear_session_response(response):
    """Remove session cookie from response"""
    response.delete_cookie(key=COOKIE_NAME)
    return response


def create_service_token(client_id: str) -> str:
    """
    Create a service token for nova_client OAuth2 authentication.

    Args:
        client_id: Client identifier to encode in the token

    Returns:
        JWT token string with type="service"
    """
    # iat lets a secret rotation end the tokens issued before it.
    return create_access_token(data={"sub": client_id, "type": "service",
                                     "iat": time.time()})


def create_session_token(username: str) -> str:
    """
    Create a session token for management UI authentication.

    Args:
        username: Username to encode in the token

    Returns:
        JWT token string with type="management"
    """
    return create_access_token(data={"sub": username, "type": "management"})


async def require_admin(current_user=Depends(get_current_user)):
    """
    Dependency that requires the current user to be an admin

    For use in Management API endpoints that need admin privileges.

    Raises:
        HTTPException: If user is not an admin
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user
