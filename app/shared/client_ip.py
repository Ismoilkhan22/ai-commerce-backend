"""Mijozning haqiqiy IP manzili — rate limit kalitlari uchun (08 §5, 22 §8).

`X-Forwarded-For` ga faqat ishonchli proksi (Nginx, shop sayti serveri — `TRUSTED_PROXIES`) yuborgan
bo'lsa ishoniladi. Zanjir o'ngdan chapga o'qiladi va birinchi ishonchsiz manzil olinadi: Nginx haqiqiy IP'ni
oxiriga qo'shadi, xaridor chap tomonga nima yozsa ham hisobga olinmaydi. Ishonchsiz manzildan kelgan XFF
umuman o'qilmaydi (QA M04 F3).

Shop sayti server tomonida (SSR) API'ni bitta IP'dan chaqiradi va xaridor IP'sini XFF'da beradi —
sayt serveri ishonchli ro'yxatda bo'lsa, 120/daq chegarasi har xaridorga alohida bo'ladi.
Xaridor IP'si kelmagan SSR so'rovi (`from_trusted_proxy`) o'z alohida chelagini oladi (08 §5).

Bir nechta `X-Forwarded-For` qatori (RFC 9110 §5.3) bitta zanjirga birlashtiriladi (QA M04 B1).
"""

from __future__ import annotations

from collections.abc import Sequence
from ipaddress import IPv4Network, IPv6Network, ip_address

from starlette.requests import Request

Networks = Sequence[IPv4Network | IPv6Network]


def _in(value: str, networks: Networks) -> bool:
    try:
        address = ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in networks)


def resolve_client_ip(peer: str | None, forwarded_for: str | None, trusted: Networks) -> str:
    """To'g'ridan ulangan manzil (`peer`) ishonchli bo'lsa — XFF'dagi o'ngdan birinchi ishonchsiz manzil."""
    if not peer:
        return "unknown"
    if not forwarded_for or not _in(peer, trusted):
        return peer
    hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
    for hop in reversed(hops):
        try:
            ip_address(hop)
        except ValueError:
            return peer  # buzilgan zanjirga ishonilmaydi
        if not _in(hop, trusted):
            return hop
    return hops[0] if hops else peer  # hammasi ishonchli proksi — eng chapdagisi


def _forwarded_for(request: Request) -> str | None:
    lines = request.headers.getlist("x-forwarded-for")
    return ", ".join(lines) if lines else None


def client_ip(request: Request) -> str:
    trusted: Networks = getattr(request.app.state, "trusted_proxies", ())
    peer = request.client.host if request.client else None
    return resolve_client_ip(peer, _forwarded_for(request), trusted)


def from_trusted_proxy(request: Request, ip: str) -> bool:
    """So'rov ishonchli proksining o'zidan keldi, xaridor IP'sisiz (masalan, sayt serverining o'z so'rovi)."""
    trusted: Networks = getattr(request.app.state, "trusted_proxies", ())
    return _in(ip, trusted)
