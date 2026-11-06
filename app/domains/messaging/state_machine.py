"""Suhbat (FSM-04) va kanal ulanishi (FSM-03) — business/05 strelkalari va DEC-137 10-qaror talqini.

AI (6-modul) hali yo'q: birinchi xabarda suhbat `AI_ACTIVE` dan darhol `HUMAN_NEEDED` ga o'tadi
(`REQUEST_HUMAN`, sabab `AI_UNAVAILABLE`), `speaker_mode = PAUSED` — hech kim avtomatik yozmaydi (12 §8).
Operator suhbatni olganda (`TAKE_OVER`) `speaker_version` +1 — AI tayyorlagan javob yuborilmaydi (TC-009).

5b kengaytmalari (business/05 ga qo'shish founder tasdig'ini kutmoqda — M05b "qarorlar"):
- operator AI'dan yoki "xaridor javobi kutilmoqda" holatidan ham suhbatni oladi (`conversation.takeover`);
- operator suhbatni javobidan keyin ham, navbatdan ham yopadi (spam);
- yopilgan suhbatni operator o'zi qayta ochadi (`REOPEN`) — birinchi bo'lib yozish uchun;
- `WAITING_CUSTOMER → AI_ACTIVE` (AI javob kutayotgan edi) — `CUSTOMER_REPLIED_TO_AI`: bitta (holat, buyruq)
  juftligi bitta strelka bo'lishi kerak (04 §3).
"""

from __future__ import annotations

from app.shared.types.actor import ActorType
from app.shared.types.state import StateMachineRule

CONVERSATION = "messaging.conversation"
CHANNEL = "messaging.channel"


def _conv(command: str, src: str, dst: str, *actors: ActorType) -> StateMachineRule:
    return StateMachineRule(
        entity_type=CONVERSATION,
        command=command,
        from_status=src,
        to_status=dst,
        actors=frozenset(actors),
        business_ref="FSM-04",
    )


def _channel(command: str, src: str, dst: str, *actors: ActorType) -> StateMachineRule:
    return StateMachineRule(
        entity_type=CHANNEL,
        command=command,
        from_status=src,
        to_status=dst,
        actors=frozenset(actors),
        business_ref="FSM-03",
    )


CONVERSATION_RULES = [
    # business/05 FSM-04
    _conv("FIRST_MESSAGE", "NEW", "AI_ACTIVE", "SYSTEM"),
    _conv("AWAIT_CUSTOMER", "AI_ACTIVE", "WAITING_CUSTOMER", "AI_AGENT"),
    _conv("REQUEST_HUMAN", "AI_ACTIVE", "HUMAN_NEEDED", "AI_AGENT", "SYSTEM", "STAFF", "CUSTOMER"),
    _conv("TAKE_OVER", "HUMAN_NEEDED", "HUMAN_ACTIVE", "STAFF"),
    _conv("AWAIT_CUSTOMER", "HUMAN_ACTIVE", "WAITING_CUSTOMER", "STAFF"),
    _conv("CUSTOMER_REPLIED", "WAITING_CUSTOMER", "HUMAN_ACTIVE", "SYSTEM"),
    _conv("RETURN_TO_AI", "HUMAN_ACTIVE", "AI_ACTIVE", "STAFF"),
    _conv("RESOLVE", "HUMAN_ACTIVE", "RESOLVED", "STAFF"),
    _conv("CUSTOMER_REPLIED", "RESOLVED", "REOPENED", "SYSTEM"),
    # DEC-137 10-qaror va 5b kengaytmalari
    _conv("CUSTOMER_REPLIED_TO_AI", "WAITING_CUSTOMER", "AI_ACTIVE", "SYSTEM"),
    _conv("TAKE_OVER", "AI_ACTIVE", "HUMAN_ACTIVE", "STAFF"),
    _conv("TAKE_OVER", "WAITING_CUSTOMER", "HUMAN_ACTIVE", "STAFF"),
    _conv("TAKE_OVER", "REOPENED", "HUMAN_ACTIVE", "STAFF"),
    _conv("REQUEST_HUMAN", "REOPENED", "HUMAN_NEEDED", "SYSTEM", "STAFF", "CUSTOMER"),
    _conv("RESOLVE", "WAITING_CUSTOMER", "RESOLVED", "STAFF"),
    _conv("RESOLVE", "HUMAN_NEEDED", "RESOLVED", "STAFF"),
    _conv("RESOLVE", "REOPENED", "RESOLVED", "STAFF"),
    _conv("REOPEN", "RESOLVED", "REOPENED", "STAFF"),
    # 6b (AI sotuvchi): operator AI'ga qaytaradi ("Resume AI") va qayta ochilgan suhbatda AI davom etadi
    _conv("RETURN_TO_AI", "HUMAN_NEEDED", "AI_ACTIVE", "STAFF"),
    _conv("RETURN_TO_AI", "WAITING_CUSTOMER", "AI_ACTIVE", "STAFF"),
    _conv("AI_RESUME", "REOPENED", "AI_ACTIVE", "SYSTEM"),
]

CHANNEL_RULES = [
    _channel("CONNECT", "PENDING", "CONNECTED", "STAFF"),
    _channel("MARK_DEGRADED", "CONNECTED", "DEGRADED", "SYSTEM"),
    _channel("RECONNECT", "DEGRADED", "CONNECTED", "STAFF", "SYSTEM"),
    _channel("DISCONNECT", "CONNECTED", "DISCONNECTED", "STAFF", "SYSTEM"),
    _channel("DISCONNECT", "DEGRADED", "DISCONNECTED", "STAFF", "SYSTEM"),
]
