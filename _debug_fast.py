import asyncio, logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from agent import _run_agent_fast_inner, _fast_ddg_search
from db import init_db, get_pool
from uuid import uuid4

async def get_real_user_id():
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM users LIMIT 1")
        if row:
            return row['id']
    return None

async def test():
    await init_db()

    # First test DDG directly
    print('=== Testing DDG ===')
    ddg = await _fast_ddg_search('帮我看一下三星医疗今天的价格')
    print(f'DDG result ({len(ddg)} chars): {ddg[:1000]}')

    # Get a real user_id
    user_id = await get_real_user_id()
    if user_id is None:
        print('ERROR: No users found in DB — cannot test fast agent')
        return
    print(f'Using user_id: {user_id}')

    print()
    print('=== Testing fast agent ===')
    tokens = []
    thoughts = []

    async def on_token(t):
        tokens.append(t)
        print(f'TOKEN: {repr(t)}', flush=True)

    async def on_thinking(src, lbl, content):
        thoughts.append(content)

    async def on_status(s):
        print(f'STATUS: {s}', flush=True)

    result = await _run_agent_fast_inner(
        '帮我看一下三星医疗今天的价格',
        user_id,
        on_status=on_status,
        on_thinking=on_thinking,
        on_token=on_token,
    )
    print(f'Result text ({len(result["text"])} chars): {result["text"][:500]}')
    print(f'Total tokens received: {len(tokens)}')
    print(f'Total thinking chunks: {len(thoughts)}')
    if thoughts:
        full_think = "".join(thoughts)
        print(f'Thinking content ({len(full_think)} chars): {full_think[:1000]}')

asyncio.run(test())
