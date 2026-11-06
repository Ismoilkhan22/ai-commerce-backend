"""Lokal demo: NoutbukUz'da AI sotuvchi SUGGEST rejimida (6b). Qayta ishga tushirish xavfsiz.

- profil (ohang, shop haqida) va 3 ta e'lon qilingan FAQ/siyosat bandi;
- LLM — `LLM_PROVIDER=fake` (standart): kalitsiz demo, "RTX 4060 bormi?" → katalogdan qidiradi va narx bilan
  taklif tayyorlaydi; inbox'da "AI taklifi" ko'rinadi. Haqiqiy model uchun — progress/M06b "Gemini kaliti".
- 6c: boshlang'ich "golden" baholash to'plami (40 holat, muzlatilgan) — platforma paneli "AI baholash".
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select

from app.config.settings import Settings
from app.db.seed.commerce_seed import _context, _services
from app.domains.sales_ai.common import DEFAULT_HANDOFF_RULES, DEFAULT_TOOLS
from app.domains.sales_ai.eval.runner import EvalEngine
from app.domains.sales_ai.eval.service import EvalService
from app.domains.sales_ai.models.orm import AgentProfileVersion, AgentSettings, KnowledgeItem
from app.platform.audit.services.audit_service import AuditService
from app.shared.clock import utcnow
from app.shared.db.encryption import configure_pii
from app.shared.db.session import Database
from app.shared.types.actor import ActorContext

PROFILE = {
    "shop_display_name": "NoutbukUz",
    "tone": "FRIENDLY",
    "about_text": "Toshkentdagi noutbuk va kompyuter ehtiyot qismlari do'koni: Chilonzor, Yunusobod, "
    "Qatortol.",
    "extra_instructions": "Avval mijozning byudjeti va maqsadini (o'yin, ish, o'qish) so'rang.",
}
KNOWLEDGE = (
    (
        "FAQ",
        "Yetkazib berish",
        "Toshkent bo'ylab 1 kun ichida, 30 000 so'm. Viloyatlarga — pochta orqali 2–4 kun.",
    ),
    ("FAQ", "Ish vaqti", "Har kuni 10:00–20:00. Filiallar: Chilonzor, Yunusobod, Qatortol."),
    (
        "POLICY",
        "Kafolat",
        "Yangi mahsulotlarga ishlab chiqaruvchi kafolati (12–36 oy). Kafolat masalasi — operator.",
    ),
)


@dataclass
class SalesAiSeedReport:
    configured: bool = False
    knowledge: int = 0
    golden_cases: int = 0  # 6c: yangi o'rnatilgan golden to'plam holatlari (bor bo'lsa — 0)


async def run_sales_ai_seed(settings: Settings) -> SalesAiSeedReport:
    configure_pii(settings.pii_keyring())
    report = SalesAiSeedReport()
    _, _, permissions = _services(settings)
    database = Database(settings.database_config())
    try:
        async with database.transaction() as db:
            evals = EvalService(cast(EvalEngine, None), AuditService())  # faqat to'plam — LLM kerak emas
            golden, created = await evals.install_golden(db, ActorContext.system())
            report.golden_cases = golden.rows if created else 0
        async with database.transaction() as db:
            ctx = await _context(db, permissions, "noutbukuz")
            if ctx is None or await db.get(AgentSettings, ctx.shop_id) is not None:
                return report
            owner = ctx.actors["OWNER"]
            profile = AgentProfileVersion(
                shop_id=ctx.shop_id,
                version=1,
                status="ACTIVE",
                content_hash=hashlib.sha256(repr(sorted(PROFILE.items())).encode()).hexdigest(),
                approved_by=owner.membership_id,
                approved_at=utcnow(),
                created_by=owner.membership_id,
                **PROFILE,
            )
            db.add(profile)
            await db.flush()
            db.add(
                AgentSettings(
                    shop_id=ctx.shop_id,
                    mode="SUGGEST",
                    active_profile_version_id=profile.id,
                    allowed_tools=DEFAULT_TOOLS,
                    handoff_rules=DEFAULT_HANDOFF_RULES,
                    daily_cost_cap_minor=500,  # $5 / kun
                    monthly_cost_cap_minor=5000,
                    updated_by=owner.membership_id,
                )
            )
            existing = await db.scalar(
                select(KnowledgeItem.id).where(KnowledgeItem.shop_id == ctx.shop_id).limit(1)
            )
            if existing is None:
                for kind, title, body in KNOWLEDGE:
                    db.add(
                        KnowledgeItem(
                            shop_id=ctx.shop_id,
                            kind=kind,
                            locale="uz",
                            title=title,
                            body=body,
                            status="APPROVED",
                            approved_by=owner.membership_id,
                            approved_at=utcnow(),
                            created_by=owner.membership_id,
                        )
                    )
                    report.knowledge += 1
            report.configured = True
    finally:
        await database.dispose()
    return report
