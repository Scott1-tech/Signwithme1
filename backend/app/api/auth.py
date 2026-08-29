from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AuthError, ConflictError
from app.core.security import (
    ROLE_ADMIN,
    ROLE_RANK,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.user import TokenOut, UserCreate, UserLogin, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    """Self-registration always creates a contractor. Elevated roles are
    assigned by an admin through /api/auth/users/{id}/role."""
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise ConflictError("An account with that email already exists")

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role="contractor",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AuthError("Incorrect email or password")
    if not user.is_active:
        raise AuthError("Account is disabled")
    return TokenOut(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/users/{user_id}/role", response_model=UserOut)
def set_role(
    user_id: str,
    role: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    if actor.role != ROLE_ADMIN:
        raise AuthError("Only an admin may change roles")
    if role not in ROLE_RANK:
        raise AuthError(f"Unknown role: {role}")
    target = db.get(User, user_id)
    if target is None:
        raise AuthError("User not found")
    target.role = role
    db.commit()
    db.refresh(target)
    return target
