# AI 八字排盘 · 产品化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给现有 AI 八字排盘引擎加上用户系统、积分制付费、邀请裂变、AI 对话面板，使其成为可上线运营的产品。

**Architecture:** 在现有 FastAPI 单文件应用上增量添加 SQLAlchemy ORM 层（SQLite）、JWT 鉴权、聚合支付集成、积分系统、邀请追踪。前端以弹层/浮层追加新功能，不重构现有页面。Docker Compose 单机部署。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x + aiosqlite, PyJWT, httpx（支付回调请求）, 阿里云短信 SDK

## Global Constraints

- 不修改现有命理逻辑（排盘、旺衰、断前事、校正模块）
- 所有数据库操作通过 SQLAlchemy ORM，禁止裸写 SQL
- 免费接口不加鉴权，付费接口加 `@require_auth` + `@require_entitlement`
- 前端改动以弹层/浮层为主，不破坏现有布局
- 积分不过期、月限 50 积分可赠出、首 3 轮 AI 对话免费试用
- 支付回调必须验签，订单 30 分钟过期，幂等处理

---

## 文件结构总览

```
项目根目录/
├── orm/
│   ├── __init__.py          # 空文件，标记为 Python 包
│   ├── db.py                # SQLAlchemy engine + session factory
│   ├── user.py              # User 表 + VerificationCode 表
│   ├── entitlement.py       # Entitlement 表
│   ├── order.py             # Order 表
│   ├── points.py            # Points 表 + PointsLog 表
│   └── invite.py            # Invite 表
├── api/
│   ├── __init__.py
│   └── routes/
│       ├── __init__.py
│       ├── auth.py          # 登录/注册/验证码发送
│       ├── payment.py       # 创建订单/支付回调
│       ├── points.py        # 积分查询/消耗/赠送
│       ├── invite.py        # 邀请链接生成/追踪
│       └── chat.py          # AI 对话（积分门控）
├── services/
│   ├── auth.py              # JWT 签发/验证 + 验证码生成/校验
│   ├── gate.py              # require_auth + require_entitlement 装饰器
│   ├── payment.py           # 聚合支付签名 + 回调验签 + 订单处理
│   └── points.py            # 积分加减/赠送/流水记录
├── main.py                  # 瘦身为路由注册入口
├── requirements.txt         # 新增 sqlalchemy, aiosqlite, pyjwt, httpx
├── Dockerfile
├── docker-compose.yml
├── nginx.conf
└── public/
    └── index.html           # 前端增量修改
```

---

## Phase 1: 基础设施（预计 3 天）

### Task 1: SQLAlchemy ORM 底座

**Files:**
- Create: `orm/__init__.py`, `orm/db.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `models.db.init_db()` → engine, `models.db.get_session()` → AsyncSession

**Changes:**

`requirements.txt` 追加：
```
sqlalchemy>=2.0
aiosqlite>=0.19
pyjwt>=2.8
httpx>=0.27
```

`orm/db.py`：
```python
"""SQLAlchemy async engine and session management."""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = "sqlite+aiosqlite:///./data/bazi.db"
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables. Call at app startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Dependency: yield an async session."""
    async with async_session() as session:
        yield session
```

- [ ] **Step 1: Install deps**

```bash
cd '/Users/lee/WorkSpace/claude项目/ai-bazi-hermes版' && pip install sqlalchemy aiosqlite pyjwt httpx
```

- [ ] **Step 2: Create orm/__init__.py (empty)**

```bash
touch orm/__init__.py
```

- [ ] **Step 3: Write orm/db.py** as above

- [ ] **Step 4: Verify imports work**

```bash
python3 -c "from models.db import Base, init_db, get_session; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add orm/__init__.py orm/db.py requirements.txt
git commit -m "feat: SQLAlchemy async engine + session factory"
```

---

### Task 2: 数据模型

**Files:**
- Create: `orm/user.py`, `orm/entitlement.py`, `orm/order.py`, `orm/points.py`, `orm/invite.py`
- Modify: `orm/db.py` (import all models so Base.metadata discovers them)

**Interfaces:**
- Produces tables: `users`, `verification_codes`, `entitlements`, `orders`, `points`, `points_logs`, `invites`

`orm/user.py`：
```python
"""User and verification code models."""
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from models.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trial_chats_remaining: Mapped[int] = mapped_column(default=3)  # 首 3 轮免费


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(default=False)
```

`orm/entitlement.py`：
```python
"""Entitlement / feature-gate model."""
from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from models.db import Base


class Entitlement(Base):
    __tablename__ = "entitlements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    feature: Mapped[str] = mapped_column(String(50), nullable=False)  # 'liuyue', 'hepan'
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

`orm/order.py`：
```python
"""Order model for payment tracking."""
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from models.db import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product: Mapped[str] = mapped_column(String(50), nullable=False)  # 'liuyue', 'points_pack', 'hepan'
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # 单位：分
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, paid, expired, cancelled
    payment_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 聚合支付订单号
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

`orm/points.py`：
```python
"""Points balance and transaction log."""
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from models.db import Base


class Points(Base):
    __tablename__ = "points"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    gifted_this_month: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PointsLog(Base):
    __tablename__ = "points_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # 正=获得，负=消耗
    reason: Mapped[str] = mapped_column(String(50), nullable=False)  # 'purchase', 'invite', 'daily', 'gift_in', 'gift_out', 'chat_cost'
    related_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # 赠送/邀请相关用户
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

`orm/invite.py`：
```python
"""Invite tracking."""
from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from models.db import Base


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    inviter_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    invitee_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # null until invitee registers
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    reward_granted: Mapped[bool] = mapped_column(default=False)  # 是否已发放积分
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 邀请完成时间
```

- [ ] **Step 1: Create all 5 model files** as above

- [ ] **Step 2: Update orm/db.py** — add import line at bottom:

```python
# At the end of orm/db.py, after the Base class:
from models.user import User, VerificationCode  # noqa: F401
from models.entitlement import Entitlement  # noqa: F401
from models.order import Order  # noqa: F401
from models.points import Points, PointsLog  # noqa: F401
from models.invite import Invite  # noqa: F401
```

- [ ] **Step 3: Verify models import**

```bash
python3 -c "from models.db import Base, init_db; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add orm/user.py orm/entitlement.py orm/order.py orm/points.py orm/invite.py orm/db.py
git commit -m "feat: 数据模型——User/Entitlement/Order/Points/Invite"
```

---

### Task 3: 在主应用挂载数据库

**Files:**
- Modify: `main.py`

**Changes:**

在 `main.py` 顶部现有 import 之后插入：

```python
from contextlib import asynccontextmanager
from models.db import init_db
```

替换 `app = FastAPI(...)` 为：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(
    title="AI八字排盘引擎",
    description="基于 lunar-python 的八字排盘 API（精度到分钟）",
    version="2.0.0",
    lifespan=lifespan,
)
```

- [ ] **Step 1: Apply changes** to main.py

- [ ] **Step 2: Verify app starts and creates DB**

```bash
cd '/Users/lee/WorkSpace/claude项目/ai-bazi-hermes版' && timeout 5 python3 main.py 2>&1 || true
```
Expected: Startup log without errors. Check `data/bazi.db` exists:
```bash
ls -la data/bazi.db
```

- [ ] **Step 3: Kill any lingering process and commit**

```bash
git add main.py
git commit -m "feat: FastAPI lifespan 加载 SQLAlchemy init_db"
```

---

## Phase 2: 用户系统（预计 2 天）

### Task 4: 验证码 + JWT 服务

**Files:**
- Create: `services/auth.py`
- Modify: `requirements.txt` (already added pyjwt in Task 1)

`services/auth.py`：
```python
"""Auth service: SMS verification code + JWT."""
import os
import random
import time
from datetime import datetime, timedelta
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models.user import User, VerificationCode

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7
CODE_LENGTH = 6
CODE_EXPIRE_MINUTES = 5
RESEND_COOLDOWN_SECONDS = 60


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
    """Get existing user by phone or create new one."""
    stmt = select(User).where(User.phone == phone)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        user = User(phone=phone)
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
```

- [ ] **Step 1: Create api/ directory and files**

```bash
mkdir -p api/routes
touch api/__init__.py api/routes/__init__.py
```

- [ ] **Step 2: Create services/auth.py** as above

- [ ] **Step 3: Verify imports**

```bash
python3 -c "from services.auth import generate_code, create_jwt, verify_jwt; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add api/ services/auth.py
git commit -m "feat: 验证码生成/发送 + JWT 签发/验证"
```

---

### Task 5: 注册/登录 API

**Files:**
- Create: `api/routes/auth.py`
- Modify: `main.py` (注册路由)

**Interfaces:**
- POST `/api/auth/send-code` — `{phone: str}` → `{ok: bool, cooldown: int | null}`
- POST `/api/auth/login` — `{phone: str, code: str}` → `{token: str, user: {id, phone, trial_chats_remaining}}`

`api/routes/auth.py`：
```python
"""Auth routes: send-code, login."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from models.db import get_session
from services.auth import create_and_send_code, verify_code, get_or_create_user, create_jwt

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SendCodeRequest(BaseModel):
    phone: str


class SendCodeResponse(BaseModel):
    ok: bool
    cooldown: int | None = None  # remaining cooldown seconds


class LoginRequest(BaseModel):
    phone: str
    code: str


class UserResponse(BaseModel):
    id: str
    phone: str
    trial_chats_remaining: int


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


@router.post("/send-code", response_model=SendCodeResponse)
async def send_code(req: SendCodeRequest, db: AsyncSession = Depends(get_session)):
    code = await create_and_send_code(db, req.phone)
    if code is None:
        return SendCodeResponse(ok=False, cooldown=60)
    return SendCodeResponse(ok=True)


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_session)):
    if not await verify_code(db, req.phone, req.code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    user = await get_or_create_user(db, req.phone)
    token = create_jwt(user.id)
    return LoginResponse(
        token=token,
        user=UserResponse(
            id=user.id,
            phone=user.phone,
            trial_chars_remaining=user.trial_chats_remaining,
        ),
    )
```

在 `main.py` 中，在 `from services.forecast import ...` 之后、`app = FastAPI(...)` 之前加入：

```python
from api.routes.auth import router as auth_router
```

在 `# 静态文件服务` 行之前加入：

```python
app.include_router(auth_router)
```

- [ ] **Step 1: Create api/routes/auth.py** as above

- [ ] **Step 2: Register route in main.py**

- [ ] **Step 3: Start server and test**

```bash
# Start server in background
cd '/Users/lee/WorkSpace/claude项目/ai-bazi-hermes版' && python3 main.py &
sleep 3

# Test send-code
curl -s -X POST http://localhost:8022/api/auth/send-code -H 'Content-Type: application/json' -d '{"phone":"13800138000"}'

# Check console for printed code, then login
curl -s -X POST http://localhost:8022/api/auth/login -H 'Content-Type: application/json' -d '{"phone":"13800138000","code":"<printed_code>"}'
```
Expected: Second curl returns `{"token":"...", "user":{...}}`

- [ ] **Step 4: Commit**

```bash
git add api/routes/auth.py main.py
git commit -m "feat: 注册/登录 API——验证码 + JWT"
```

---

### Task 6: 鉴权门控中间件

**Files:**
- Create: `services/gate.py`

**Interfaces:**
- `require_auth` — FastAPI Depends: extracts JWT, raises 401 if invalid
- `require_entitlement(feature: str)` — FastAPI Depends factory: checks entitlements table

`services/gate.py`：
```python
"""Auth gate: require_auth + require_entitlement decorators as FastAPI dependencies."""
from fastapi import Header, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models.db import get_session
from models.entitlement import Entitlement
from services.auth import verify_jwt


async def require_auth(authorization: str = Header(None), db: AsyncSession = Depends(get_session)) -> str:
    """Extract and verify JWT. Returns user_id. Raises 401."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization[7:]
    user_id = verify_jwt(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user_id


def require_entitlement(feature: str):
    """Factory: returns a dependency that checks user has purchased a feature."""
    async def check(user_id: str = Depends(require_auth), db: AsyncSession = Depends(get_session)) -> str:
        stmt = select(Entitlement).where(
            Entitlement.user_id == user_id,
            Entitlement.feature == feature,
        )
        result = await db.execute(stmt)
        if not result.scalars().first():
            raise HTTPException(status_code=402, detail=f"请先解锁此功能")
        return user_id
    return check
```

- [ ] **Step 1: Create services/gate.py** as above

- [ ] **Step 2: Verify import**

```bash
python3 -c "from services.gate import require_auth, require_entitlement; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add services/gate.py
git commit -m "feat: require_auth + require_entitlement 门控中间件"
```

---

## Phase 3: 支付系统（预计 3 天）

### Task 7: 支付服务

**Files:**
- Create: `services/payment.py`

**Interfaces:**
- `create_order(db, user_id, product, amount)` → Order
- `verify_callback(data, sign)` → bool
- `process_paid_order(db, order)` → void (updates entitlements + points)

`services/payment.py`：
```python
"""Payment service: order creation, callback verification, fulfillment."""
import hashlib
import hmac
import os
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from models.order import Order
from models.entitlement import Entitlement
from models.points import Points, PointsLog

# xorpay 聚合支付配置（示例——替换为实际商户参数）
XORPAY_APP_ID = os.getenv("XORPAY_APP_ID", "")
XORPAY_API_SECRET = os.getenv("XORPAY_API_SECRET", "")
XORPAY_BASE_URL = "https://xorpay.com/api"

# 产品定义
PRODUCTS = {
    "liuyue": {"name": "流月详批", "amount": 990, "points": 100},  # 金额单位：分
    "points_pack": {"name": "积分补充包", "amount": 690, "points": 100},
    "hepan": {"name": "合盘", "amount": 1800, "points": 0},
}


async def create_payment_link(order: Order, return_url: str = "") -> str | None:
    """Call xorpay to create a payment link. Returns payment URL or None."""
    payload = {
        "app_id": XORPAY_APP_ID,
        "out_trade_no": order.id,
        "total_amount": order.amount,
        "subject": PRODUCTS.get(order.product, {}).get("name", "命理服务"),
        "return_url": return_url,
    }
    # Sign the payload
    payload["sign"] = _sign(payload, XORPAY_API_SECRET)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(f"{XORPAY_BASE_URL}/pay", json=payload)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("pay_url")
        except Exception:
            pass
    return None


def verify_callback(data: dict, sign: str) -> bool:
    """Verify xorpay callback signature."""
    expected = _sign(data, XORPAY_API_SECRET)
    return hmac.compare_digest(expected, sign)


async def process_paid_order(db: AsyncSession, order: Order):
    """Fulfill a paid order: grant entitlements + points."""
    order.status = "paid"
    from datetime import datetime
    order.paid_at = datetime.utcnow()

    product = PRODUCTS.get(order.product, {})
    points_to_add = product.get("points", 0)

    # Grant entitlement for the product (except points_pack which only adds points)
    if order.product in ("liuyue", "hepan"):
        db.add(Entitlement(user_id=order.user_id, feature=order.product))

    # Add points
    if points_to_add > 0:
        pts = await db.get(Points, order.user_id)
        if not pts:
            pts = Points(user_id=order.user_id, balance=0)
            db.add(pts)
            await db.flush()
        pts.balance += points_to_add
        db.add(PointsLog(
            user_id=order.user_id,
            amount=points_to_add,
            reason="purchase",
        ))

    await db.commit()


def _sign(data: dict, secret: str) -> str:
    """Sign data with MD5 (common for Chinese payment providers)."""
    # Remove sign key if present, sort keys, concat, append secret, MD5
    items = sorted([(k, v) for k, v in data.items() if k != "sign"])
    raw = "&".join([f"{k}={v}" for k, v in items]) + secret
    return hashlib.md5(raw.encode()).hexdigest()
```

- [ ] **Step 1: Create services/payment.py** as above

- [ ] **Step 2: Commit**

```bash
git add services/payment.py
git commit -m "feat: 支付服务——订单创建/回调验签/履约"
```

---

### Task 8: 支付 API 路由

**Files:**
- Create: `api/routes/payment.py`
- Modify: `main.py` (注册路由)

`api/routes/payment.py`：
```python
"""Payment routes: create order, callback."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from models.db import get_session
from models.order import Order
from services.gate import require_auth
from services.payment import create_payment_link, verify_callback, process_paid_order, PRODUCTS

router = APIRouter(prefix="/api/payment", tags=["payment"])


class CreateOrderRequest(BaseModel):
    product: str  # 'liuyue', 'points_pack', 'hepan'


class CreateOrderResponse(BaseModel):
    order_id: str
    pay_url: str | None


@router.post("/create-order", response_model=CreateOrderResponse)
async def create_order(
    req: CreateOrderRequest,
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    if req.product not in PRODUCTS:
        raise HTTPException(status_code=400, detail="未知产品")

    product = PRODUCTS[req.product]
    order = Order(
        user_id=user_id,
        product=req.product,
        amount=product["amount"],
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    pay_url = await create_payment_link(order)
    return CreateOrderResponse(order_id=order.id, pay_url=pay_url)


@router.post("/callback")
async def payment_callback(request: Request, db: AsyncSession = Depends(get_session)):
    """xorpay 支付回调——无需鉴权（由聚合支付服务器调用）"""
    data = await request.json()
    sign = data.get("sign", "")

    if not verify_callback(data, sign):
        raise HTTPException(status_code=400, detail="签名验证失败")

    order_id = data.get("out_trade_no")
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    if order.status != "pending":
        return {"status": "ok"}  # 幂等

    await process_paid_order(db, order)
    return {"status": "ok"}
```

在 `main.py` 中加入：

```python
from api.routes.payment import router as payment_router
# ...后文加
app.include_router(payment_router)
```

- [ ] **Step 1: Create api/routes/payment.py** as above

- [ ] **Step 2: Register routes in main.py**

- [ ] **Step 3: Test create-order (requires JWT)**

```bash
# Login first, get token
TOKEN=$(curl -s -X POST http://localhost:8022/api/auth/login ... | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# Create order
curl -s -X POST http://localhost:8022/api/payment/create-order \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"product":"liuyue"}'
```
Expected: `{"order_id":"...", "pay_url": null}` (pay_url null 因为没有真实商户密钥，但 order_id 应该存在)

- [ ] **Step 4: Commit**

```bash
git add api/routes/payment.py main.py
git commit -m "feat: 支付 API——创建订单 + 回调验签"
```

---

## Phase 4: 积分系统（预计 1 天）

### Task 9: 积分服务 + API

**Files:**
- Create: `services/points.py`（积分业务逻辑）
- Create: `api/routes/points.py`
- Modify: `main.py` (注册路由)

**Interfaces:**
- GET `/api/points/balance` → `{balance, gifted_this_month}`（需登录）
- POST `/api/points/gift` → `{ok}`（需登录，月限 50）
- 内部函数 `consume_points(db, user_id, amount, reason)` → bool

`services/points.py`：
```python
"""Points business logic."""
from sqlalchemy.ext.asyncio import AsyncSession
from models.points import Points, PointsLog


async def get_balance(db: AsyncSession, user_id: str) -> Points:
    """Get or create points record."""
    pts = await db.get(Points, user_id)
    if not pts:
        pts = Points(user_id=user_id, balance=0)
        db.add(pts)
        await db.flush()
    return pts


async def consume_points(db: AsyncSession, user_id: str, amount: int, reason: str) -> bool:
    """Consume points. Returns True if sufficient balance."""
    if amount <= 0:
        return True
    pts = await get_balance(db, user_id)
    if pts.balance < amount:
        return False
    pts.balance -= amount
    db.add(PointsLog(user_id=user_id, amount=-amount, reason=reason))
    await db.commit()
    return True


async def add_points(db: AsyncSession, user_id: str, amount: int, reason: str, related_user_id: str | None = None):
    """Add points."""
    pts = await get_balance(db, user_id)
    pts.balance += amount
    db.add(PointsLog(
        user_id=user_id,
        amount=amount,
        reason=reason,
        related_user_id=related_user_id,
    ))
    await db.commit()


async def gift_points(db: AsyncSession, from_user_id: str, to_user_id: str, amount: int) -> bool:
    """Gift points. Checks monthly limit (50). Returns True on success."""
    if amount <= 0:
        return False
    from_pts = await get_balance(db, from_user_id)
    if from_pts.balance < amount:
        return False
    if from_pts.gifted_this_month + amount > 50:
        return False

    from_pts.balance -= amount
    from_pts.gifted_this_month += amount
    db.add(PointsLog(user_id=from_user_id, amount=-amount, reason="gift_out", related_user_id=to_user_id))

    to_pts = await get_balance(db, to_user_id)
    to_pts.balance += amount
    db.add(PointsLog(user_id=to_user_id, amount=amount, reason="gift_in", related_user_id=from_user_id))

    await db.commit()
    return True
```

`api/routes/points.py`：
```python
"""Points API routes."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from models.db import get_session
from services.gate import require_auth
from services import points as points_svc

router = APIRouter(prefix="/api/points", tags=["points"])


class BalanceResponse(BaseModel):
    balance: int
    gifted_this_month: int


class GiftRequest(BaseModel):
    to_user_id: str
    amount: int


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    pts = await points_svc.get_balance(db, user_id)
    return BalanceResponse(balance=pts.balance, gifted_this_month=pts.gifted_this_month)


@router.post("/gift")
async def gift_points(
    req: GiftRequest,
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    ok = await points_svc.gift_points(db, user_id, req.to_user_id, req.amount)
    if not ok:
        raise HTTPException(status_code=400, detail="积分不足或超过本月赠送限额")
    return {"ok": True}
```

- [ ] **Step 1: Create both files** as above

- [ ] **Step 2: Register in main.py** (同前模式)

- [ ] **Step 3: Commit**

```bash
git add services/points.py api/routes/points.py main.py
git commit -m "feat: 积分系统——查询/消耗/赠送 API"
```

---

## Phase 5: 邀请系统（预计 1 天）

### Task 10: 邀请 API

**Files:**
- Create: `api/routes/invite.py`
- Modify: `main.py`

**Interfaces:**
- POST `/api/invite/create-link` → `{invite_url}`（需登录）
- GET `/api/invite/track/{token}` → `{inviter_id}`（无需登录，存 token）

`api/routes/invite.py`：
```python
"""Invite routes."""
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from models.db import get_session
from models.invite import Invite
from services.gate import require_auth

router = APIRouter(prefix="/api/invite", tags=["invite"])


class CreateLinkResponse(BaseModel):
    invite_token: str
    invite_url: str


@router.post("/create-link", response_model=CreateLinkResponse)
async def create_invite_link(
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    token = secrets.token_urlsafe(32)
    invite = Invite(inviter_id=user_id, token=token)
    db.add(invite)
    await db.commit()
    url = f"/invite/{token}"  # 前端路由
    return CreateLinkResponse(invite_token=token, invite_url=url)


@router.get("/track/{token}")
async def track_invite(token: str, db: AsyncSession = Depends(get_session)):
    """Public endpoint: resolve invite token to inviter ID."""
    from sqlalchemy import select
    stmt = select(Invite).where(Invite.token == token)
    result = await db.execute(stmt)
    invite = result.scalars().first()
    if not invite:
        raise HTTPException(status_code=404, detail="邀请链接无效")
    return {"inviter_id": invite.inviter_id}
```

- [ ] **Step 1: Create api/routes/invite.py** as above

- [ ] **Step 2: Register in main.py**

- [ ] **Step 3: Commit**

```bash
git add api/routes/invite.py main.py
git commit -m "feat: 邀请系统——创建链接 + token 解析"
```

---

## Phase 6: AI 对话（预计 1 天）

### Task 11: AI 对话 API（积分门控）

**Files:**
- Create: `api/routes/chat.py`
- Modify: `main.py`

**Interfaces:**
- POST `/api/chat` → `{reply, trial_remaining | points_remaining}`（需登录，积分门控）

`api/routes/chat.py`：
```python
"""AI chat route with points gating."""
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from models.db import get_session
from models.user import User
from services.gate import require_auth
from services.points import consume_points, get_balance

router = APIRouter(prefix="/api/chat", tags=["chat"])

# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
CHAT_COST = 5  # 积分/轮


class ChatRequest(BaseModel):
    message: str
    context: str = ""  # 命盘摘要上下文


class ChatResponse(BaseModel):
    reply: str
    trial_remaining: int | None = None  # 试用剩余次数
    points_remaining: int | None = None  # 积分剩余


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    user = await db.get(User, user_id)

    # Check trial first
    if user.trial_chats_remaining > 0:
        user.trial_chats_remaining -= 1
        await db.commit()
        reply = await _call_deepseek(req.message, req.context)
        return ChatResponse(reply=reply, trial_remaining=user.trial_chats_remaining)

    # Consume points
    ok = await consume_points(db, user_id, CHAT_COST, "chat_cost")
    if not ok:
        raise HTTPException(status_code=402, detail="积分不足，请购买积分")

    reply = await _call_deepseek(req.message, req.context)
    pts = await get_balance(db, user_id)
    return ChatResponse(reply=reply, points_remaining=pts.balance)


async def _call_deepseek(message: str, context: str) -> str:
    """Call DeepSeek API."""
    import httpx

    system_prompt = (
        "你是专业的八字命理师，基于用户提供的命盘信息进行分析。"
        "回答要专业但易懂，引用典籍时注明出处。"
        f"用户命盘摘要：{context}" if context else "请先完成排盘和校准。"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.7,
                },
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            return "抱歉，AI 暂时不可用，请稍后再试。"
```

- [ ] **Step 1: Create api/routes/chat.py** as above

- [ ] **Step 2: Register in main.py**

- [ ] **Step 3: Commit**

```bash
git add api/routes/chat.py main.py
git commit -m "feat: AI 对话 API——试用 + 积分门控 + DeepSeek 调用"
```

---

## Phase 7: 前端（预计 4 天）

### Task 12: 登录弹层

**Files:**
- Modify: `public/index.html`

**Changes** — 在现有页面中追加登录弹层 HTML + JS：

在 `<body>` 内、`#app-shell` 之后插入：

```html
<!-- 登录弹层 -->
<div id="auth-modal" class="modal" hidden>
  <div class="modal-bg" onclick="closeAuthModal()"></div>
  <div class="modal-card">
    <h3>登录 / 注册</h3>
    <p class="modal-desc">使用手机号登录，解锁全部功能</p>
    <input id="auth-phone" type="tel" placeholder="手机号" maxlength="11">
    <div class="code-row">
      <input id="auth-code" type="text" placeholder="验证码" maxlength="6">
      <button id="send-code-btn" class="btn btn-secondary" onclick="sendCode()">获取验证码</button>
    </div>
    <button class="btn btn-primary btn-lg" onclick="doLogin()" id="login-btn">登录</button>
    <p id="auth-msg" class="auth-msg"></p>
  </div>
</div>
```

追加 JS 逻辑（在现有 `<script>` 块内或新 `<script>` 标签）：

```javascript
// ============ Auth ============
let AUTH_TOKEN = sessionStorage.getItem('bazi_token') || '';
let AUTH_USER = JSON.parse(sessionStorage.getItem('bazi_user') || 'null');

function openAuthModal() {
  document.getElementById('auth-modal').hidden = false;
}

function closeAuthModal() {
  document.getElementById('auth-modal').hidden = true;
}

async function sendCode() {
  const phone = document.getElementById('auth-phone').value.replace(/\s/g, '');
  if (!/^1\d{10}$/.test(phone)) { alert('请输入正确的手机号'); return; }
  const btn = document.getElementById('send-code-btn');
  btn.disabled = true;
  try {
    const res = await apiFetch('/api/auth/send-code', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone }),
    });
    if (!res.ok) throw new Error('发送失败');
    // 倒计时
    let sec = 59;
    const tick = setInterval(() => {
      btn.textContent = sec + 's';
      if (--sec < 0) { clearInterval(tick); btn.textContent = '重新获取'; btn.disabled = false; }
    }, 1000);
  } catch (e) {
    alert('发送失败，请稍后再试');
    btn.disabled = false;
  }
}

async function doLogin() {
  const phone = document.getElementById('auth-phone').value.replace(/\s/g, '');
  const code = document.getElementById('auth-code').value.trim();
  if (!phone || !code) { alert('请输入手机号和验证码'); return; }
  try {
    const data = await apiFetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone, code }),
    });
    AUTH_TOKEN = data.token;
    AUTH_USER = data.user;
    sessionStorage.setItem('bazi_token', AUTH_TOKEN);
    sessionStorage.setItem('bazi_user', JSON.stringify(AUTH_USER));
    closeAuthModal();
    updateAuthUI();
  } catch (e) {
    document.getElementById('auth-msg').textContent = '验证码错误或已过期';
  }
}

function updateAuthUI() {
  const btn = document.getElementById('auth-btn');
  if (!btn) return;
  if (AUTH_USER) {
    btn.textContent = AUTH_USER.phone.slice(-4);
    btn.onclick = showUserMenu;
  } else {
    btn.textContent = '登录';
    btn.onclick = openAuthModal;
  }
}

async function authFetch(url, opts = {}) {
  opts.headers = opts.headers || {};
  if (AUTH_TOKEN) opts.headers['Authorization'] = 'Bearer ' + AUTH_TOKEN;
  return apiFetch(url, opts);
}

function logout() {
  AUTH_TOKEN = '';
  AUTH_USER = null;
  sessionStorage.removeItem('bazi_token');
  sessionStorage.removeItem('bazi_user');
  updateAuthUI();
}

// 初始化
document.addEventListener('DOMContentLoaded', updateAuthUI);
```

追加 CSS（在现有 `<style>` 块内）：

```css
/* Auth modal */
.modal { position: fixed; inset: 0; z-index: 200; display: flex; align-items: center; justify-content: center; }
.modal[hidden] { display: none; }
.modal-bg { position: absolute; inset: 0; background: rgba(0,0,0,0.6); }
.modal-card { position: relative; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 28px; width: min(380px, 90vw); display: flex; flex-direction: column; gap: 14px; }
.modal-card h3 { font-size: 1.1rem; color: var(--ink); }
.modal-desc { font-size: 0.82rem; color: var(--muted); }
.modal-card input { width: 100%; padding: 10px 14px; border-radius: var(--radius-sm); border: 1px solid var(--line); background: var(--bg-mid); color: var(--ink); font-size: 0.9rem; }
.code-row { display: flex; gap: 8px; }
.code-row input { flex: 1; }
.auth-msg { color: var(--wx-huo); font-size: 0.82rem; text-align: center; }
```

- [ ] **Step 1: 追加 HTML + CSS + JS** 到 index.html

- [ ] **Step 2: 在 topbar 加登录按钮**

在 `.top-actions` 内加：
```html
<button id="auth-btn" class="btn btn-ghost" onclick="openAuthModal()">登录</button>
```

- [ ] **Step 3: 端到端测试**

在浏览器中：点击登录 → 输入手机号 → 获取验证码 → 输入验证码 → 登录成功显示后四位

- [ ] **Step 4: Commit**

```bash
git add public/index.html
git commit -m "feat: 登录弹层——手机验证码 + JWT 存储"
```

---

### Task 13: 支付弹层 + 积分中心 + AI 对话面板

**Files:**
- Modify: `public/index.html`

由于这三个前端任务都改同一个文件且互相依赖，**合并为一个 task**，分三步提交。

**支付弹层**——流月详批/积分包/合盘的购买入口，调 `/api/payment/create-order`，拿到 pay_url 后跳转或弹 iframe。

**积分中心**——显示余额 + 签到 + 赠送入口，调 `/api/points/*`。

**AI 对话面板**——右侧滑出聊天面板，显示试用剩余/积分余额，调 `/api/chat`。

具体 HTML/CSS/JS 从略（代码量大，实现时按 spec 逐功能写），核心逻辑已在前面 task 中定义的后端接口里覆盖。

- [ ] **Step 1: 支付弹层** — HTML 嵌入 #auth-modal 旁，JS 函数 `openPayModal(product)`, `doPay()`

- [ ] **Step 2: 积分中心** — 顶部导航栏右侧积分 badge，点击弹出积分中心

- [ ] **Step 3: AI 对话面板** — 右侧滑出面板，消息列表 + 输入框，5 积分/轮消耗

- [ ] **Step 4: 端到端测试完整付费链路**：登录 → 购买流月 → 积分到账 → AI 对话消耗积分

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat: 支付弹层 + 积分中心 + AI 对话面板"
```

---

## Phase 8: 部署（预计 2 天）

### Task 14: Dockerfile + docker-compose

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `nginx.conf`

`Dockerfile`：
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8022
CMD ["python3", "main.py"]
```

`docker-compose.yml`：
```yaml
version: '3.8'
services:
  app:
    build: .
    ports:
      - "8022:8022"
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - JWT_SECRET=${JWT_SECRET}
      - XORPAY_APP_ID=${XORPAY_APP_ID}
      - XORPAY_API_SECRET=${XORPAY_API_SECRET}
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

`nginx.conf`：
```nginx
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://app:8022;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

- [ ] **Step 1: Create Dockerfile, docker-compose.yml, nginx.conf**

- [ ] **Step 2: Test build**

```bash
cd '/Users/lee/WorkSpace/claude项目/ai-bazi-hermes版' && docker compose build
```
Expected: build success.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml nginx.conf .env.example
git commit -m "feat: Docker 部署——Dockerfile + compose + nginx"
```

---

## 实施优先级（一个月时间盒）

| 周 | Phase | 交付物 |
|---|---|---|
| Week 1 | Phase 1 + 2 | SQLAlchemy ORM + 数据模型 + 用户注册登录 API |
| Week 2 | Phase 3 | 支付创建订单 + 回调 + 门控 |
| Week 3 | Phase 4 + 5 + 6 | 积分 API + 邀请 API + AI 对话 API |
| Week 4 | Phase 7 + 8 | 前端（登录+支付+对话面板）+ Docker 部署 |

---

## 测试清单

- [ ] 注册/登录/退出 全流程
- [ ] 未登录访问付费接口 → 401
- [ ] 已登录但未购买 → 402
- [ ] 购买流月 → 积分到账 → entitlements 写入
- [ ] AI 对话消耗积分 → 余额扣减正确
- [ ] 积分不足时对话 → 402 提示
- [ ] 前三轮试用不扣积分
- [ ] 支付回调幂等（同一订单多次回调不重复加积分）
- [ ] 邀请链接 → 被邀者注册 → 邀请人得积分
- [ ] 月赠积分上限 50

---

## 不需要做的

- 小程序（先 H5）
- 会员订阅制
- 后台管理系统
- CI/CD 流水线
- 邮件/第三方 OAuth 登录
- WebSocket 实时推送
