"""Auth sozlamalari (ADR-023, 10 §5). Settings'dan main.py da yig'iladi va app.state'da turadi."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class AuthConfig:
    jwt_secret: str
    jwt_issuer: str = "commerce-os"
    access_token_ttl: timedelta = timedelta(minutes=15)
    refresh_token_ttl: timedelta = timedelta(days=30)  # har yangilanishda yana 30 kun
    login_max_failures: int = 5
    login_lockout: timedelta = timedelta(minutes=15)
    invite_ttl: timedelta = timedelta(hours=72)
    password_reset_ttl: timedelta = timedelta(hours=24)
    app_public_url: str = "http://localhost:3000"  # taklif va tiklash havolalari shu manzilga
    platform_app_public_url: str = "http://localhost:3001"  # platforma jamoasi havolalari
    cookie_secure: bool = True
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65_536
    argon2_parallelism: int = 4
