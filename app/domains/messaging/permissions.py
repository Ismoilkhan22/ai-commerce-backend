"""messaging ruxsatlari va rollar (10 §6.4, business/04 "Suhbatlar va inbox", UAT-M09).

Ikkinchi qatlam service'da (10 §6.8): operator (SALES) — **own**: o'ziga biriktirilgan suhbatlar va
biriktirilmagan navbat (oladi). Omborchi xaridor suhbatlarini ko'rmaydi (business/04).
"""

from __future__ import annotations

from collections.abc import Mapping

CHANNEL_VIEW = "messaging.channel.view"
CHANNEL_CONNECT = "messaging.channel.connect"  # faqat ega kanal ulaydi (UAT-M09)
CONVERSATION_VIEW = "messaging.conversation.view"
CONVERSATION_REPLY = "messaging.conversation.reply"
CONVERSATION_TAKEOVER = "messaging.conversation.takeover"
CONVERSATION_ASSIGN = "messaging.conversation.assign"
CONVERSATION_RESOLVE = "messaging.conversation.resolve"
HANDOFF_REQUEST = "messaging.handoff.request"

_OPERATOR = frozenset(
    {CONVERSATION_VIEW, CONVERSATION_REPLY, CONVERSATION_TAKEOVER, CONVERSATION_RESOLVE, HANDOFF_REQUEST}
)
_MANAGER = _OPERATOR | {CHANNEL_VIEW, CONVERSATION_ASSIGN}
_OWNER = _MANAGER | {CHANNEL_CONNECT}

MESSAGING_PERMISSIONS = sorted(_OWNER)

MESSAGING_ROLE_GRANTS: Mapping[str, frozenset[str]] = {
    "OWNER": _OWNER,
    "MANAGER": _MANAGER,
    "SALES": _OPERATOR,
}
