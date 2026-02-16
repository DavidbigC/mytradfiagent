"""Create the admin account (davidc). Run once on a fresh server."""

import asyncio
from db import init_db, get_pool
from auth import hash_password


async def main():
    await init_db()

    username = "davidc"
    password = input("Set password for admin account (davidc): ").strip()
    if len(password) < 6:
        print("Password must be at least 6 characters.")
        return

    display_name = input("Display name (press Enter for 'davidc'): ").strip() or "davidc"
    pw_hash = hash_password(password)

    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM web_accounts WHERE username = $1", username
        )
        if exists:
            print(f"Account '{username}' already exists.")
            return

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

    print(f"Admin account '{username}' created.")


if __name__ == "__main__":
    asyncio.run(main())
