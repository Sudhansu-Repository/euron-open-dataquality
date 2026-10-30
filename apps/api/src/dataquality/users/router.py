from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter

from dataquality.auth.dependencies import Admin, SignedIn
from dataquality.auth.schemas import UserOut
from dataquality.core.deps import SessionDep
from dataquality.users import service
from dataquality.users.models import User
from dataquality.users.schemas import UserCreate, UserUpdate

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=list[UserOut], summary="List users (to add them to projects)")
async def list_users(_: SignedIn, session: SessionDep) -> Sequence[User]:
    return await service.list_users(session)


@router.post("", response_model=UserOut, status_code=201, summary="Create a user (admins)")
async def create_user(body: UserCreate, actor: Admin, session: SessionDep) -> User:
    return await service.create_user(session, body, actor)


@router.patch("/{user_id}", response_model=UserOut, summary="Update a user's name, role or access")
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, actor: Admin, session: SessionDep
) -> User:
    return await service.update_user(session, user_id, body, actor)
