"""
Caching utilities for FPD API responses

Provides TTL (Time-To-Live) caching for search results to reduce API calls
and improve performance for repeated queries.
"""

import hashlib
import json
import time
from typing import Any, Dict, Optional
from .safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

try:
    from cachetools import TTLCache
    CACHETOOLS_AVAILABLE = True
except ImportError:
    CACHETOOLS_AVAILABLE = False
    logger.warning("cachetools not available - caching disabled")


class SimpleCache:
    """Simple in-memory cache with TTL when cachetools is not available"""

    def __init__(self, maxsize: int = 100, ttl: int = 300):
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache: Dict[str, tuple] = {}  # key -> (value, expiry_time)
        self._access_order = []  # LRU tracking

    def get(self, key: str) -> Optional[Any]:
        """Get item from cache if not expired"""
        if key in self._cache:
            value, expiry_time = self._cache[key]
            if time.time() < expiry_time:
                # Move to end for LRU
                self._access_order.remove(key)
                self._access_order.append(key)
                return value
            else:
                # Expired - remove
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
        return None

    def set(self, key: str, value: Any) -> None:
        """Set item in cache with TTL"""
        expiry_time = time.time() + self.ttl

        # Remove if already exists
        if key in self._cache:
            self._access_order.remove(key)

        # Add new item
        self._cache[key] = (value, expiry_time)
        self._access_order.append(key)

        # Evict oldest if over capacity
        while len(self._cache) > self.maxsize:
            oldest_key = self._access_order.pop(0)
            if oldest_key in self._cache:
                del self._cache[oldest_key]

    def clear(self) -> None:
        """Clear all cached items"""
        self._cache.clear()
        self._access_order.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        valid_items = 0
        expired_items = 0
        current_time = time.time()

        for key, (value, expiry_time) in self._cache.items():
            if current_time < expiry_time:
                valid_items += 1
            else:
                expired_items += 1

        return {
            "total_items": len(self._cache),
            "valid_items": valid_items,
            "expired_items": expired_items,
            "maxsize": self.maxsize,
            "ttl_seconds": self.ttl
        }


class CacheManager:
    """Manages caching for FPD API responses"""

    def __init__(self, maxsize: int = 100, ttl: int = 300):
        """
        Initialize cache manager

        Args:
            maxsize: Maximum number of cached items
            ttl: Time-to-live in seconds (default 5 minutes)
        """
        self.ttl = ttl

        if CACHETOOLS_AVAILABLE:
            self.cache = TTLCache(maxsize=maxsize, ttl=ttl)
            logger.info(f"Initialized TTLCache with maxsize={maxsize}, ttl={ttl}s")
        else:
            self.cache = SimpleCache(maxsize=maxsize, ttl=ttl)
            logger.info(f"Initialized SimpleCache with maxsize={maxsize}, ttl={ttl}s")

    def _generate_cache_key(self, method_name: str, *args, **kwargs) -> str:
        """Generate a cache key from method name and arguments"""
        # Create a deterministic key from method name and arguments
        key_data = {
            'method': method_name,
            'args': args,
            'kwargs': sorted(kwargs.items())  # Sort for deterministic ordering
        }

        key_string = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.md5(key_string.encode()).hexdigest()

    def get(self, method_name: str, *args, **kwargs) -> Optional[Any]:
        """Get cached result for method call"""
        cache_key = self._generate_cache_key(method_name, *args, **kwargs)
        return self.cache.get(cache_key)

    def set(self, method_name: str, result: Any, *args, **kwargs) -> None:
        """Cache result for method call"""
        cache_key = self._generate_cache_key(method_name, *args, **kwargs)

        # Don't cache error responses
        if isinstance(result, dict) and result.get('error'):
            return

        if hasattr(self.cache, 'set'):
            self.cache.set(cache_key, result)
        else:
            # cachetools' TTLCache is a MutableMapping with no .set() —
            # item assignment applies the TTL
            self.cache[cache_key] = result
        logger.debug(f"Cached result for {method_name} with key {cache_key[:8]}...")

    def clear(self) -> None:
        """Clear all cached items"""
        self.cache.clear()
        logger.info("Cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if CACHETOOLS_AVAILABLE and hasattr(self.cache, 'currsize'):
            return {
                "current_size": self.cache.currsize,
                "max_size": self.cache.maxsize,
                "ttl_seconds": self.ttl,
                "cache_type": "TTLCache"
            }
        elif hasattr(self.cache, 'get_stats'):
            stats = self.cache.get_stats()
            stats["cache_type"] = "SimpleCache"
            return stats
        else:
            return {"cache_type": "Unknown", "ttl_seconds": self.ttl}
