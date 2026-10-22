"""Composition root: domenlararo Query Port implementatsiyalari va DI provider'lar (02 §2, ADR-032).

`app.workers` bilan birga domenlarni import qila oladigan yagona joy. Domenlar faqat
`app/shared/contracts/` dagi interfeyslarni biladi; ulanish shu yerda bo'ladi (S1 dan boshlab).
"""

from __future__ import annotations

from app.config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
