"""Kesh (08 §4): Redis (ishlab chiqarish) yoki xotira (testlar, lokal) — bitta interfeys.

Kalitlar faqat `keys.py` orqali quriladi — shop kalitida `shop_id` prefiksi majburiy (08 §4.1).
"""

from app.shared.cache.backends import Cache, MemoryCache, RedisCache

__all__ = ["Cache", "MemoryCache", "RedisCache"]
