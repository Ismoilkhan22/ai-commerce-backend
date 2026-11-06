"""Lokal demo: NoutbukUz'da leadlar va takliflar (6a). Qayta ishga tushirish xavfsiz.

- L-1 → T-1 yuborilgan (havola tokeni chiqarilmaydi — panelda "Yuborish" ni qayta bosing);
- L-2 → T-2 qabul qilingan (xodim belgiladi) → DRAFT buyurtma (source QUOTE);
- L-3 — biriktirilmagan, navbatda (operator o'ziga oladi).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from app.config.settings import Settings
from app.db.seed.commerce_seed import _context, _services
from app.domains.commerce.quotes.models.orm import Lead
from app.domains.commerce.quotes.schemas import LeadCreate, QuoteCreate, QuoteLineIn, Requirements
from app.shared.db.encryption import configure_pii
from app.shared.db.session import Database


@dataclass
class QuotesSeedReport:
    leads: int = 0
    quotes: int = 0


async def run_quotes_seed(settings: Settings) -> QuotesSeedReport:
    configure_pii(settings.pii_keyring())
    report = QuotesSeedReport()
    svc, _, permissions = _services(settings)
    database = Database(settings.database_config())
    try:
        async with database.transaction() as db:
            ctx = await _context(db, permissions, "noutbukuz")
            if ctx is None:
                return report
            if await db.scalar(select(func.count()).select_from(Lead).where(Lead.shop_id == ctx.shop_id)):
                return report
            manager = ctx.actors.get("MANAGER", ctx.actors["OWNER"])
            sales = ctx.actors.get("SALES", manager)
            office = [
                QuoteLineIn(sku_id=ctx.skus["NB-HP-250G10"]),
                QuoteLineIn(sku_id=ctx.skus["NB-LEN-IPS3-15"]),
            ]
            workplace = [
                QuoteLineIn(sku_id=ctx.skus["NB-HP-250G10"], qty=2),
                QuoteLineIn(sku_id=ctx.skus["NB-ASUS-TUF-A15"]),
            ]
            for name, phone, lines, accept in (
                ("Dilnoza Karimova", None, office, False),
                ("Bek Office MChJ", "+998901234500", workplace, True),  # rozilik bilan — buyurtmaga o'tadi
            ):
                lead = await svc.leads.create(
                    db,
                    sales,
                    LeadCreate(
                        customer_name=name,
                        contact_phone=phone,
                        consent_contact=phone is not None,
                        requirements=Requirements(budget_minor=1_500_000_000, workloads=["OFFICE"]),
                    ),
                )
                quote = await svc.quotes.create(db, sales, QuoteCreate(lead_id=lead.id, lines=lines))
                quote = await svc.quotes.submit(db, sales, quote.id, quote.version)
                if quote.status == "REVIEW":
                    quote = await svc.quotes.approve(db, manager, quote.id, quote.version, None)
                quote, _token = await svc.quotes.send(db, sales, quote.id, quote.version)
                if accept:
                    await svc.quotes.accept_by_staff(db, sales, quote.id, quote.version)
                report.leads += 1
                report.quotes += 1
            await svc.leads.create(
                db,
                manager,
                LeadCreate(
                    customer_name="Sardor (Telegram)",
                    requirements=Requirements(budget_minor=900_000_000, workloads=["GAMING_1080P"]),
                ),
            )
            report.leads += 1
    finally:
        await database.dispose()
    return report
