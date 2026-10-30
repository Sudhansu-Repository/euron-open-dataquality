"""HTTP endpoints for organisation settings and self sign-up."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from redis.exceptions import RedisError

from dataquality.auth.dependencies import Admin
from dataquality.auth.router import _session
from dataquality.auth.schemas import SignInOut
from dataquality.core.deps import ContainerDep, SessionDep, client_ip
from dataquality.core.errors import RateLimitedError
from dataquality.limits.limiter import LimitDecision
from dataquality.org import service
from dataquality.org.schemas import AdminSettings, PublicSettings, SettingsUpdate, SignupRequest

router = APIRouter(prefix="/api/v1", tags=["org"])
SIGNUP_RPM_PER_IP = 10


@router.get("/org/public", response_model=PublicSettings, summary="Settings the sign-in page needs")
async def public_settings(session: SessionDep) -> PublicSettings:
    from sqlalchemy import select

    from dataquality.users.models import User

    out = service.public(await service.get(session))
    out.needs_setup = not await session.scalar(select(User.id).limit(1))
    return out


@router.get("/org/settings", response_model=AdminSettings, summary="Organisation settings")
async def get_settings(_: Admin, session: SessionDep) -> AdminSettings:
    return service.admin(await service.get(session))


@router.patch("/org/settings", response_model=AdminSettings, summary="Change organisation settings")
async def update_settings(
    body: SettingsUpdate, actor: Admin, session: SessionDep, container: ContainerDep
) -> AdminSettings:
    return service.admin(await service.update(container, session, body, actor))


@router.post(
    "/auth/signup",
    response_model=SignInOut,
    status_code=201,
    summary="Create an account (the first one is the admin) and sign in",
)
async def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    container: ContainerDep,
    session: SessionDep,
) -> SignInOut:
    ip = client_ip(request)
    try:
        decision = await container.kv.hit(f"signup:{ip}", SIGNUP_RPM_PER_IP)
    except (RedisError, OSError):
        decision = LimitDecision(allowed=True)
    if not decision.allowed:
        raise RateLimitedError(
            "Too many sign-ups from this address. Wait a minute and try again",
            headers={"retry-after": str(decision.retry_after_s)},
        )
    user = await service.signup(session, body, ip)
    response.headers["cache-control"] = "no-store"
    return _session(response, container, user)
