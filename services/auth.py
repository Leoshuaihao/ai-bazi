"""Auth service: username+password + JWT."""
import os
import hashlib
import secrets
import random
import time
from datetime import datetime, timedelta
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from orm.user import User, VerificationCode

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is required. Please set a random 256-bit key.")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7
CODE_LENGTH = 6
CODE_EXPIRE_MINUTES = 5
RESEND_COOLDOWN_SECONDS = 60
PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """Hash password with PBKDF2 + SHA256 + salt."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2:sha256:{PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against PBKDF2 hash."""
    try:
        parts = password_hash.split(":")
        if len(parts) != 3:
            return False
        _, _, rest = parts  # rest = "iterations$salt$hex"
        iters_str, salt, expected = rest.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters_str))
        return dk.hex() == expected
    except (ValueError, AttributeError):
        return False


async def register_user(db: AsyncSession, username: str, password: str) -> User | None:
    """Register a new user. Returns User or None if username taken."""
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalars().first():
        return None
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def login_user(db: AsyncSession, username: str, password: str) -> User | None:
    """Authenticate user by username + password. Returns User or None."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if not user or not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.utcnow()
    await db.commit()
    return user


def generate_code() -> str:
    return "".join([str(random.randint(0, 9)) for _ in range(CODE_LENGTH)])


async def send_sms(phone: str, code: str) -> bool:
    """Send SMS via Aliyun. Replace with real SDK call in production.
    Returns True on success.
    """
    # TODO: Replace with actual Aliyun SMS SDK call
    # For now, print to console (development mode)
    print(f"[SMS] To: {phone}, Code: {code}")
    return True


async def create_and_send_code(db: AsyncSession, phone: str) -> str | None:
    """Create verification code and send SMS. Returns code or None if cooldown."""
    # Check cooldown
    stmt = select(VerificationCode).where(
        VerificationCode.phone == phone,
        VerificationCode.created_at > datetime.utcnow() - timedelta(seconds=RESEND_COOLDOWN_SECONDS)
    ).order_by(VerificationCode.created_at.desc())
    result = await db.execute(stmt)
    recent = result.scalars().first()
    if recent:
        return None  # Still in cooldown

    code = generate_code()
    expires_at = datetime.utcnow() + timedelta(minutes=CODE_EXPIRE_MINUTES)

    vc = VerificationCode(phone=phone, code=code, expires_at=expires_at)
    db.add(vc)
    await db.commit()

    await send_sms(phone, code)
    return code


async def verify_code(db: AsyncSession, phone: str, code: str) -> bool:
    """Verify SMS code. Marks it as used on success."""
    stmt = select(VerificationCode).where(
        VerificationCode.phone == phone,
        VerificationCode.code == code,
        VerificationCode.used == False,
        VerificationCode.expires_at > datetime.utcnow(),
    ).order_by(VerificationCode.created_at.desc())
    result = await db.execute(stmt)
    vc = result.scalars().first()
    if not vc:
        return False
    vc.used = True
    await db.commit()
    return True


async def get_or_create_user(db: AsyncSession, phone: str) -> User:
    """Get existing user by phone or create new one (legacy SMS flow)."""
    stmt = select(User).where(User.phone == phone)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        # Legacy phone-only user: generate username from phone
        username = "u" + phone[-6:]
        # Ensure unique
        i = 0
        while True:
            check = await db.execute(select(User).where(User.username == username))
            if not check.scalars().first():
                break
            i += 1
            username = f"u{phone[-6:]}_{i}"
        user = User(
            username=username,
            password_hash=hash_password(phone),  # phone as temp password
            phone=phone,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        user.last_login_at = datetime.utcnow()
        await db.commit()
    return user


def create_jwt(user_id: str) -> str:
    """Create JWT token."""
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> str | None:
    """Verify JWT, return user_id or None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
