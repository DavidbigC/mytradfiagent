from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import get_pool
from auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterBody(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/register")
async def register(body: RegisterBody):
    username = body.username.strip()
    password = body.password
    if len(username) < 2 or len(password) < 6:
        raise HTTPException(400, "Username must be >=2 chars, password >=6 chars")

    display_name = (body.display_name or username).strip()
    pw_hash = hash_password(password)

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check username taken
        exists = await conn.fetchval(
            "SELECT 1 FROM web_accounts WHERE username = $1", username
        )
        if exists:
            raise HTTPException(409, "Username already taken")

        # Create user + platform_account + web_account in transaction
        async with conn.transaction():
            user_id = await conn.fetchval(
                "INSERT INTO users (display_name) VALUES ($1) RETURNING id",
                display_name,
            )
            await conn.execute(
                "INSERT INTO platform_accounts (user_id, platform, platform_uid) VALUES ($1, 'web', $2)",
                user_id, username,
            )
            await conn.execute(
                "INSERT INTO web_accounts (user_id, username, password_hash) VALUES ($1, $2, $3)",
                user_id, username, pw_hash,
            )

    token = create_access_token(user_id, username)
    return {
        "token": token,
        "user": {"user_id": str(user_id), "username": username, "display_name": display_name},
    }


@router.post("/login")
async def login(body: LoginBody):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, username, password_hash FROM web_accounts WHERE username = $1",
            body.username.strip(),
        )
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Invalid username or password")

    user_id: UUID = row["user_id"]
    username: str = row["username"]

    # Update last_active
    pool = await get_pool()
    async with pool.acquire() as conn:
        display_name = await conn.fetchval(
            "UPDATE users SET last_active_at = now() WHERE id = $1 RETURNING display_name",
            user_id,
        )

    token = create_access_token(user_id, username)
    return {
        "token": token,
        "user": {"user_id": str(user_id), "username": username, "display_name": display_name or username},
    }


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT display_name FROM users WHERE id = $1", user["user_id"]
        )
    return {
        "user_id": str(user["user_id"]),
        "username": user["username"],
        "display_name": row["display_name"] if row else user["username"],
    }
