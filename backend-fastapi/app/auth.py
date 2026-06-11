from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Iterable
import hashlib, hmac
import jwt
from .config import JWT_SECRET, JWT_ALGORITHM, JWT_EXP_MINUTES
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select
from .db import User, get_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/auth/login')

ROLE_ORDER = {'viewer': 1, 'developer': 2, 'architect': 3, 'admin': 4}

def hash_password(password: str) -> str:
    # Lightweight demo-safe hash. For enterprise prod, replace with argon2/bcrypt + password policy.
    digest = hashlib.sha256((JWT_SECRET + ':' + password).encode()).hexdigest()
    return 'sha256$' + digest

def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), password_hash)

def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        'sub': str(user.id),
        'email': user.email,
        'role': user.role,
        'iat': int(now.timestamp()),
        'exp': int((now + timedelta(minutes=JWT_EXP_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def user_from_token(token: str, s: Session) -> User:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload['sub'])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='invalid token')
    user = s.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='inactive or missing user')
    return user

def current_user(token: str = Depends(oauth2_scheme), s: Session = Depends(get_session)) -> User:
    return user_from_token(token, s)

def require_role(*roles: str):
    allowed = set(roles)
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail=f'requires role: {sorted(allowed)}')
        return user
    return dep

def require_min_role(role: str):
    min_rank = ROLE_ORDER[role]
    def dep(user: User = Depends(current_user)) -> User:
        if ROLE_ORDER.get(user.role, 0) < min_rank:
            raise HTTPException(status_code=403, detail=f'requires minimum role: {role}')
        return user
    return dep

def seed_demo_users(s: Session) -> None:
    users = [
        ('admin@fundsafe.local', 'Admin User', 'admin', 'admin123'),
        ('architect@fundsafe.local', 'Architect Reviewer', 'architect', 'architect123'),
        ('dev@fundsafe.local', 'Developer User', 'developer', 'dev123'),
        ('viewer@fundsafe.local', 'Viewer User', 'viewer', 'viewer123'),
    ]
    for email, full_name, role, password in users:
        exists = s.exec(select(User).where(User.email == email)).first()
        if not exists:
            s.add(User(email=email, full_name=full_name, role=role, password_hash=hash_password(password)))
    s.commit()
