import asyncio
import time
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

_cache: dict[str, dict] = {}
_cache_lock = asyncio.Lock()

DEFAULT_TTL = 300  # 5 minutes
MAX_CACHE_SIZE = 200  # evict oldest entries when exceeded


def cache_key(func_name: str, args) -> str:
    """Generate cache key from function name and args (supports dict, list, and primitives)."""
    if isinstance(args, dict):
        raw = f"{func_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"
    else:
        raw = f"{func_name}:{json.dumps(args, ensure_ascii=False, default=str)}"
    return hashlib.md5(raw.encode()).hexdigest()


def _evict_expired():
    """Remove expired entries and oldest if over size limit. Must be called under _cache_lock."""
    now = time.time()
    expired = [k for k, v in _cache.items() if now - v["ts"] >= v["ttl"]]
    for k in expired:
        del _cache[k]

    # If still over limit, evict oldest
    if len(_cache) > MAX_CACHE_SIZE:
        sorted_keys = sorted(_cache, key=lambda k: _cache[k]["ts"])
        for k in sorted_keys[:len(_cache) - MAX_CACHE_SIZE]:
            del _cache[k]


def get_cached(func_name: str, args) -> dict | None:
    key = cache_key(func_name, args)
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < entry["ttl"]:
        logger.info(f"Cache HIT: {func_name}")
        return entry["result"]
    # Don't mutate here without lock — just return None and let set_cached handle cleanup
    return None


async def set_cached(func_name: str, args, result, ttl: int = DEFAULT_TTL):
    async with _cache_lock:
        _evict_expired()
        key = cache_key(func_name, args)
        _cache[key] = {"result": result, "ts": time.time(), "ttl": ttl}


def cached(ttl: int = DEFAULT_TTL):
    """Decorator to add caching to an async tool function."""
    def decorator(func):
        async def wrapper(**kwargs):
            hit = get_cached(func.__name__, kwargs)
            if hit is not None:
                return hit
            result = await func(**kwargs)
            # Don't cache errors
            if not (isinstance(result, dict) and "error" in result):
                await set_cached(func.__name__, kwargs, result, ttl)
            return result
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator
