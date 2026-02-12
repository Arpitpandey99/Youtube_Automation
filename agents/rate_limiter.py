"""
Token-bucket rate limiter for API providers.
Prevents hitting rate limits across all external services.
"""

import time
import threading


class RateLimiter:
    """Thread-safe token-bucket rate limiter."""

    def __init__(self, calls_per_minute: int, provider_name: str):
        self.calls_per_minute = calls_per_minute
        self.provider_name = provider_name
        self.interval = 60.0 / calls_per_minute
        self.tokens = calls_per_minute
        self.max_tokens = calls_per_minute
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        new_tokens = elapsed / self.interval
        if new_tokens > 0:
            self.tokens = min(self.max_tokens, self.tokens + new_tokens)
            self.last_refill = now

    def acquire(self):
        """Block until a token is available, then consume it."""
        while True:
            with self._lock:
                self._refill()
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
            wait = self.interval - (time.monotonic() - self.last_refill)
            if wait > 0:
                time.sleep(wait)

    def reset(self):
        """Reset the limiter to full capacity."""
        with self._lock:
            self.tokens = self.max_tokens
            self.last_refill = time.monotonic()


# Pre-configured limiters for each provider
RATE_LIMITS = {
    "replicate": RateLimiter(5, "replicate"),       # 6/min actual, 5 with margin
    "openai": RateLimiter(20, "openai"),
    "openai_tts": RateLimiter(10, "openai_tts"),
    "youtube": RateLimiter(5, "youtube"),
    "instagram": RateLimiter(2, "instagram"),
    "elevenlabs": RateLimiter(3, "elevenlabs"),
    "huggingface": RateLimiter(5, "huggingface"),
    "pexels": RateLimiter(10, "pexels"),
}


def get_limiter(provider: str) -> RateLimiter:
    """Get the rate limiter for a given provider."""
    if provider not in RATE_LIMITS:
        raise ValueError(f"Unknown provider: {provider}. Available: {list(RATE_LIMITS.keys())}")
    return RATE_LIMITS[provider]
