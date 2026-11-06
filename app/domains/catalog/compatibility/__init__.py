"""PC moslik engine'i (engineering/17): toza, deterministik qoidalar.

DB'ga yozmaydi — natijani chaqiruvchi saqlaydi.
"""

from app.domains.catalog.compatibility.engine import check
from app.domains.catalog.compatibility.model import RULESET_VERSION, Build, Part
from app.domains.catalog.compatibility.power import estimate_power_w, recommended_psu_w

__all__ = ["RULESET_VERSION", "Build", "Part", "check", "estimate_power_w", "recommended_psu_w"]
