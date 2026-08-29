"""Password hashing, JWT issuance and the current-user dependency."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import get_db
from app.core.exceptions import AuthError, PermissionError_
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)

ROLE_ADMIN = "admin"
ROLE_REVIEWER = "reviewer"
ROLE_CONTRACTOR = "contractor"
ROLE_RANK = {ROLE_CONTRACTOR: 0, ROLE_REVIEWER: 1, ROLE_ADMIN: 2}


def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd_context.verify(raw, hashed)


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise AuthError("Invalid or expired token") from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise AuthError("Missing bearer token")
    payload = decode_token(credentials.credentials)
    user = db.get(User, UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthError("User not found or inactive")
    return user


def require_role(*roles: str):
    """Dependency factory: allow the given roles, or anything ranked above them."""
    minimum = min(ROLE_RANK[r] for r in roles)

    def _dependency(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK.get(user.role, -1) < minimum:
            raise PermissionError_(f"Requires one of: {', '.join(roles)}")
        return user

    return _dependency


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
