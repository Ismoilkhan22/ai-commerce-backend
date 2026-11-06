"""AI javobini tekshirish (14 §8, M06 §6.3) — yuborishdan oldin. Ikki qatlam:

1. **Deterministik** (shu fayl, tarmoqsiz, har javobda):
   - narx: javobdagi har pul summasi (`3 500 000`, `3,5 mln`, `4.5m so'm`, `сўм`, `$350`, `UZS 1 250 000`)
     normallashtiriladi va shu navbatdagi tool narxiga aynan teng bo'lishi kerak — aks holda `PRICE_MISMATCH`;
   - mahsulot: javobdagi GPU/CPU model nomi (RTX 4060, i5-12400F, Ryzen 5 7600 …) shu navbatda tool
     qaytargan nomda yoki qidiruv so'rovida bo'lishi kerak — `UNVERIFIED_PRODUCT`;
   - qoldiq: "bor / omborda / в наличии / in stock" — faqat shu navbatda IN_STOCK/LOW_STOCK bo'lgan SKU
     uchun; tugagan mahsulotga "bor" — `STOCK_UNVERIFIED`;
   - moslik: ijobiy da'vo faqat shu navbatdagi PASS bilan, salbiy da'vo — moslik tekshiruvidan keyin;
     har gap bo'lagi alohida (inkor boshqa bo'lakdagi da'voni yashirmaydi) — `COMPAT_UNVERIFIED`;
   - chegirma (`DISCOUNT_MENTION`), buyurtma/bron/to'lov va "kafolatlaymiz" da'volari (`FORBIDDEN_CLAIM`) —
     to'rt yozuvda: o'zbek lotin, o'zbek kirill, rus, ingliz. Kafolat muddati ("12 oy kafolat") faqat tool
     qaytargan muddat bo'lsa ruxsat.
2. **LLM tekshiruvchi** (`claim_check.py`) — deterministik qatlam o'tkazib yuborgan iboralar uchun.

Yiqilsa — bitta qayta yozish, yana yiqilsa — operatorga (`VALIDATION_FAILED`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

IN_STOCK = frozenset({"IN_STOCK", "LOW_STOCK"})


@dataclass
class TurnFacts:
    prices: set[Decimal] = field(default_factory=set)  # so'm
    prices_usd: set[Decimal] = field(default_factory=set)
    titles: set[str] = field(default_factory=set)
    queries: set[str] = field(default_factory=set)
    availability: dict[str, str] = field(default_factory=dict)  # sarlavha → IN_STOCK | LOW_STOCK | …
    warranty_months: set[int] = field(default_factory=set)
    stock_checked: bool = False
    compat_decisions: set[str] = field(default_factory=set)


# ------------------------------------------------------------------ normallashtirish
def _norm(text: str) -> str:
    text = re.sub(r"[\u00a0\u2007\u2009\u202f\u200a\u2002\u2003]", " ", text)  # nbsp, thin, narrow nbsp…
    return re.sub(r"[ʻʼ‘’`´]", "'", text).lower()


def _key(text: str) -> str:
    """Model nomini solishtirish uchun: kichik harf, bo'shliq va chiziqlarsiz."""
    return re.sub(r"[\s\-_]", "", _norm(text))


# ------------------------------------------------------------------ pul summalari
_NUM = r"(?P<num>\d{1,3}(?:[ .,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_PRE = r"(?P<pre>\$|uzs|usd|so'm|сўм|сум)?\s?"
_MUL = (
    r"(?:\s?(?P<mul>mlrd|миллиард|mln|million|millions|миллион\w*|млн|ming|минг|тыс\.?|тысяч\w*|k|m)\b\.?)?"
)
_CUR = r"(?:\s?(?P<cur>so'm\w*|сўм\w*|сум\w*|som\b|sum\b|uzs|usd|\$|dollar\w*|доллар\w*))?"
_AMOUNT = re.compile(rf"(?<![\w.,#№]){_PRE}{_NUM}{_MUL}{_CUR}", re.IGNORECASE)
_UNIT_AFTER = re.compile(
    r"^\s?(gb|tb|mb|гб|тб|mhz|ghz|мгц|ггц|hz|гц|w\b|vt\b|вт|mm|мм|sm\b|cm|см|ta\b|dona|шт|штук|pcs|"
    r"oy|ой|мес|month|yil|йил|год|year|%|rpm|fps|nits|inch|дюйм|\"|-?core|ядер|потоков|thread|bit|бит|"
    r"x\b|х\b|v\b|в\b|°|ms\b|мс\b|kg|кг|g\b|гр|-?uy|-?xonadon|-?kv|"
    r"mah\b|мач\b|wh\b|soat\w*|соат\w*|час\w*|saat\b|model\b|модель\b|indeks|индекс|artikul|артикул)",
    re.IGNORECASE,
)
# Telefon raqami pul emas: +998 90 123 45 67, 998901234567, mahalliy 90 123 45 67
_PHONE = re.compile(
    r"\+\s?\d[\d\s\-()]{7,}\d|(?<![\d.,])998[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?![\d])|"
    r"(?<![\d.,])\(?\d{2}\)?[\s\-]\d{3}[\s\-]\d{2}[\s\-]\d{2}(?![\d.,])"
)
# "Model 12345", "Indeks 100000", "Artikul: 55555" — yorliqli raqam (valyutasiz) pul emas
_LABEL_BEFORE = re.compile(
    r"(?:model|modeli|indeks|index|artikul|sku|kod|kodi|code|id|seriya|serial|модель|индекс|артикул|код|арт\.?|"
    r"mod\.?|part\s?number|p/?n|s/n)\s*[:\-#№]?\s*$"
)
_MULTIPLIER = {
    "mlrd": 10**9,
    "миллиард": 10**9,
    "mln": 10**6,
    "million": 10**6,
    "millions": 10**6,
    "млн": 10**6,
    "m": 10**6,
    "ming": 10**3,
    "минг": 10**3,
    "k": 10**3,
}


def _number(raw: str) -> Decimal | None:
    grouped = re.fullmatch(r"(\d{1,3}(?:[ .,]\d{3})+)([.,]\d{1,2})?", raw)
    try:
        if grouped:
            value = Decimal(re.sub(r"\D", "", grouped.group(1)))
            if grouped.group(2):
                value += Decimal("0." + grouped.group(2)[1:])
            return value
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class Amount:
    value: Decimal
    currency: str  # UZS | USD
    text: str


def extract_amounts(text: str) -> list[Amount]:
    """Javobdagi pul summalari. Birlik (GB, W, oy, ta…) bilan kelgan son — pul emas."""
    norm = _PHONE.sub(" ", _norm(text))
    out: list[Amount] = []
    models = [m.span() for m in _MODEL.finditer(norm)]
    for match in _AMOUNT.finditer(norm):
        if any(start < match.end() and match.start() < end for start, end in models):
            continue  # "i5-12400F", "RTX 4060" — model nomi, pul emas
        num = match.group("num")
        pre, mul, cur = match.group("pre"), match.group("mul"), match.group("cur")
        mul_word = (mul or "").lower().rstrip(".")
        if mul_word in ("k", "m") and not (cur or pre):
            mul_word = ""  # "4k monitor", "8m" — pul emas
        grouped = bool(re.fullmatch(r"\d{1,3}(?:[ .,]\d{3})+(?:[.,]\d{1,2})?", num))
        plain_big = bool(re.fullmatch(r"\d{5,}", num))
        marked = bool(pre or cur or mul_word)
        if not marked:
            if _LABEL_BEFORE.search(norm[: match.start()]):
                continue
            rest = norm[match.end() :]
            if _UNIT_AFTER.match(rest) or re.match(r"[a-zа-яўқғҳ]", rest):
                continue
            if not (grouped or plain_big):
                continue
        value = _number(num)
        if value is None:
            continue
        factor = next((v for k, v in _MULTIPLIER.items() if mul_word.startswith(k)), None)
        if mul_word.startswith(("тыс", "тысяч")):
            factor = 10**3
        if mul_word.startswith("миллион"):
            factor = 10**6
        if factor:
            value *= factor
        usd = any(
            s and (s == "$" or s.startswith(("usd", "dollar", "доллар"))) for s in (pre, (cur or "").lower())
        )
        out.append(Amount(value.normalize(), "USD" if usd else "UZS", match.group().strip()))
    return out


def _mask_titles(norm: str, facts: TurnFacts) -> str:
    """Ma'lum mahsulot sarlavhalarini olib tashlaydi: "RTX 4060 AI 12345" dagi "12345" narx emas."""
    for title in sorted(facts.titles, key=len, reverse=True):
        words = _norm(title).split()
        if words:
            norm = re.sub(r"\s+".join(map(re.escape, words)), " ", norm)
    return norm


def _price_ok(amount: Amount, facts: TurnFacts) -> bool:
    pool = facts.prices_usd if amount.currency == "USD" else facts.prices
    return any(amount.value == Decimal(p).normalize() for p in pool)


# ------------------------------------------------------------------ mahsulot nomlari
_MODEL = re.compile(
    r"\b(?:rtx|gtx|rx|arc)\s?-?\d{3,4}(?:\s?(?:ti|super|xtx|xt|gre))*\b"
    r"|\bi[3579]\s?-?\s?\d{4,5}[a-z]{0,2}\b"
    r"|\bryzen\s?[3579]\s?\d{4}[a-z0-9]{0,3}\b"
    r"|\bcore\s?ultra\s?[3579]\s?\d{3}[a-z]?\b",
    re.IGNORECASE,
)


def model_tokens(text: str) -> list[str]:
    return [_key(m.group()) for m in _MODEL.finditer(_norm(text))]


def _known_product(token: str, facts: TurnFacts) -> bool:
    return any(token in _key(t) for t in facts.titles) or any(token in _key(q) for q in facts.queries)


# ------------------------------------------------------------------ leksikonlar (uz-Latn, uz-Cyrl, ru, en)
_DISCOUNT = re.compile(
    r"chegirma|чегирма|skidka|скидк|aksiya|акци[яиюй]|discount|promo\s?code|промокод|special price|"
    r"maxsus narx|махсус нарх|особ\w* цен|arzonlashtir|арзонлаштир|"
    r"\d+\s?%\s?(?:arzon|kam|chegirma|off|скидк|дешев|арзон|кам)|%\s?off\b|\b\d+\s?%\s?off|"
    r"arzonroq\s+(?:beramiz|beraman|qilib|qilamiz|sotamiz|to'laysiz)|"
    r"арзонроқ\s+(?:берамиз|бераман|қилиб|қиламиз|сотамиз|тўлайсиз)|"
    r"kamaytir\w*\s+(?:beramiz|beraman|qilamiz)|камайтир\w*\s+(?:берамиз|бераман|қиламиз)|"
    r"narx\w*\s+(?:tushir|kamaytir)|нарх\w*\s+(?:тушир|камайтир)|kam\s+to'laysiz|кам\s+тўлайсиз|"
    r"diskont|дисконт|promo\s?kod\w*|промо\s?код|"
    r"сниз\w*\s+цен|скин\w*\s+\d|уступ\w*|дешевле\s+отда|cheaper\s+for\s+you|price\s+(?:cut|drop)\s+for\s+you",
    re.IGNORECASE,
)
_CLAIM = re.compile(
    r"tasdiqlandi|tasdiqladik|tasdiqlab\s+qo'ydik|rasmiylashtirildi|rasmiylashtirdik|"
    r"band\s+qil(?:indi|dik|ib\s+qo'ydik)|bron\s?qil|to'landi|to'lov\s+qabul|"
    r"тасдиқланди|тасдиқладик|расмийлаштирилди|расмийлаштирдик|банд\s+қил(?:инди|дик)|брон\s?қил|тўланди|"
    r"подтвержд[её]н|подтвердили|оформлен|оформили|забронир|оплачен|"
    r"\bconfirmed\b|\bbooked\b|reserved\s+for\s+you|has\s+been\s+(?:placed|paid|reserved)|\bis\s+placed\b|"
    r"order\s+(?:is\s+)?placed|been\s+paid|\bsecured\b|"
    r"kafolatla\w*|kafolat\s+ber\w*|кафолатла\w*|кафолат\s+бер\w*|"
    r"гарантируем|гарантирую|даём\s+гарант\w*|даем\s+гарант\w*|we\s+guarantee|i\s+guarantee|guaranteed|"
    r"100\s?%\s?(?:kafolat|кафолат|гарант|garant|warranty|guarantee)|"
    r"(?:kafolat|кафолат|гарант\w*|garantiya|warranty|guarantee)\w*\s*[:\-]?\s*100\s?%|"
    r"lifetime\s+(?:warranty|guarantee)|umrbod|умрбод|пожизненн\w*|"
    r"\d+\s?(?:kun|кун|день|дн|day)\w*\s+(?:[\w']+\s+){0,2}(?:kafolat|кафолат|гарант|warranty|guarantee)|"
    r"(?:money[- ]back|qaytarish)\s+(?:guarantee|kafolat)|"
    r"buyurtma\w*\s+(?:yaratil\w*|berildi)|буюртма\w*\s+(?:яратил\w*|берилди)|"
    r"заказ\s*(?:№|#|n)?\s*\d*\s*(?:создан|оформлен)\w*|"
    r"order\s*(?:#|no\.?)?\s*\d*\s*(?:is\s+|has\s+been\s+)?(?:created|submitted)|"
    r"rasmiylashtirdi[mk]|расмийлаштирдим|"
    r"to'lovni\s+qabul\s+qil(?:indi|dik|dim)|тўловни\s+қабул\s+қил(?:инди|дик|дим)|оплат\w*\s+(?:принят|получен|поступил)\w*|"
    r"деньги\s+(?:получил|приняли|поступил)\w*|пул\w*\s+(?:олдик|тушди)|pul(?:ni)?\s+(?:oldik|tushdi|qabul\s+qildik)|"
    r"payment\s+(?:received|confirmed|successful|accepted)|(?:received|got)\s+(?:your\s+)?(?:payment|money)",
    re.IGNORECASE,
)
_BARE_GUARANTEE = re.compile(r"\bg(?:w)?arantiya\w*", re.IGNORECASE)  # "garantiya": faqat tool muddati bilan
_ORDER_WORD = re.compile(r"buyurtma|буюртма|zakaz|заказ|order", re.IGNORECASE)
_RECEIVED = re.compile(r"qabul\s+qilindi|қабул\s+қилинди|принят|received", re.IGNORECASE)
_WARRANTY_TERM = re.compile(
    r"(\d+)\s?(oy|ой|мес\w*|month\w*|yil|йил|год\w*|лет|year\w*)\w*\s*(?:lik\s*)?"
    r"(?:kafolat|кафолат|гарант|g(?:w)?arant|warranty)"
    r"|(?:kafolat|кафолат|гарант\w*|g(?:w)?arantiya|warranty)\w*\s*(?:muddati|муддати|срок\w*|period|:|-)?\s*(\d+)\s?"
    r"(oy|ой|мес\w*|month\w*|yil|йил|год\w*|лет|year\w*)",
    re.IGNORECASE,
)

# ------------------------------------------------------------------ qoldiq va moslik
_SENTENCE = re.compile(r"[.!?\n;]+")
_CLAUSE = re.compile(
    r",?\s*\b(?:lekin|ammo|biroq|лекин|аммо|бироқ|но|однако|but|however)\b|[,—–]", re.IGNORECASE
)
_STOCK_STRONG = re.compile(
    r"omborda|omborimizda|sotuvda|омборда|омборимизда|сотувда|в\s+наличии|на\s+складе|in\s+stock|"
    r"olib\s+ketishingiz\s+mumkin|олиб\s+кетишингиз\s+мумкин",
    re.IGNORECASE,
)
_STOCK_WEAK = re.compile(
    r"\bbor\b|\bmavjud\b|\bбор\b|\bмавжуд\b|\bесть\b|\bимеется\b|\bavailable\b|\bwe\s+have\b|\bhave\s+it\b",
    re.IGNORECASE,
)
_STOCK_NEG = re.compile(
    r"yo'q|mavjud\s+emas|qolmagan|tugagan|topilmadi|йўқ|мавжуд\s+эмас|қолмаган|тугаган|топилмади|"
    r"\bнет\b|отсутству|закончил|не\s+найден|out\s+of\s+stock|not\s+available|unavailable|sold\s+out|"
    r"don't\s+have|do\s+not\s+have|not\s+found",
    re.IGNORECASE,
)
_QUANTITY = re.compile(
    r"\b\d+\s?(?:ta|dona|та|дона|шт|штук|pcs|units?)\b|albatta|албатта|конечно|of\s+course|^\s*(?:ha|да|yes)\b",
    re.IGNORECASE,
)
_PART_STEM = (
    r"(?:plat|protsessor|xotira|korpus|quvvat|blok|videokart|soket|sovutgich|плат|процессор|хотира|корпус|"
    r"қувват|блок|видеокарт|сокет|кулер)"
)
_COMPAT_POS = re.compile(
    rf"mos\s+kel|{_PART_STEM}\w*ga\s+mos|bir-?biriga\s+mos|мос\s+кел|{_PART_STEM}\w*га\s+мос|совместим|"
    r"подходи?т\b|подойд[её]т|сочета|работа\w*\s+вместе|compatible|works\s+with|will\s+fit|\bfits?\b|"
    r"work\s+together|birga\s+ishlaydi|бирга\s+ишлайди",
    re.IGNORECASE,
)
_COMPAT_STRONG = re.compile(  # "plataga mos" — bitta qism nomi ham munosabatni bildiradi
    rf"совместим|compatible|bir-?biriga\s+mos|work\s+together|вместе|birga\s+ishlaydi|бирга\s+ишлайди|"
    rf"{_PART_STEM}\w*ga\s+mos|{_PART_STEM}\w*га\s+мос",
    re.IGNORECASE,
)
_COMPAT_NEG = re.compile(
    r"mos\s+kelmaydi|mos\s+emas|мос\s+келмайди|мос\s+эмас|несовместим|не\s+подход|не\s+подойд|"
    r"not\s+compatible|incompatible|won't\s+fit|doesn't\s+fit|does\s+not\s+fit",
    re.IGNORECASE,
)
_PART = re.compile(
    r"plata|protsessor|\bcpu\b|\bgpu\b|\bram\b|xotira|korpus|quvvat|blok|videokarta|soket|socket|sovutgich|"
    r"\bssd\b|\bpsu\b|плат|процессор|памят|корпус|блок|видеокарт|сокет|кулер|xотира|хотира|қувват|"
    r"motherboard|processor|memory|\bcase\b|power\s+supply|cooler|qism|қисм|комплект|сборк|yig'ma|йиғма|"
    r"вместе|together|birga|бирга",
    re.IGNORECASE,
)


def _clauses(text: str) -> list[str]:
    out: list[str] = []
    for sentence in _SENTENCE.split(text):
        out.extend(c for c in _CLAUSE.split(sentence) if c and c.strip())
    return out


def _stock_codes(text: str, facts: TurnFacts) -> list[str]:
    for sentence in _SENTENCE.split(_norm(text)):
        if not sentence.strip() or _STOCK_NEG.search(sentence):
            continue
        tokens = model_tokens(sentence)
        strong = bool(_STOCK_STRONG.search(sentence))
        weak = bool(_STOCK_WEAK.search(sentence)) and (bool(tokens) or bool(_QUANTITY.search(sentence)))
        if not (strong or weak):
            continue
        named = [
            status
            for title, status in facts.availability.items()
            if any(token in _key(title) for token in tokens)
        ]
        if named:
            if any(status not in IN_STOCK for status in named):
                return ["STOCK_UNVERIFIED"]
            continue
        if tokens:  # nomi bor, lekin shu navbatda qoldig'i tekshirilmagan mahsulot
            return ["STOCK_UNVERIFIED"]
        if not any(status in IN_STOCK for status in facts.availability.values()):
            return ["STOCK_UNVERIFIED"]
    return []


def _compat_codes(text: str, facts: TurnFacts) -> list[str]:
    for clause in _clauses(_norm(text)):
        negative = bool(_COMPAT_NEG.search(clause))
        positive = not negative and bool(_COMPAT_POS.search(clause))
        if not (positive or negative):
            continue
        parts = {m.group().lower() for m in _PART.finditer(clause)}
        if negative and not parts:
            continue
        if positive and not (len(parts) >= 2 or _COMPAT_STRONG.search(clause)):
            continue  # "sizga mos noutbuk", "bu karta sizga подойдёт" — moslik da'vosi emas
        if positive and "PASS" not in facts.compat_decisions:
            return ["COMPAT_UNVERIFIED"]
        if negative and not facts.compat_decisions:
            return ["COMPAT_UNVERIFIED"]
    return []


def _claim_codes(text: str, facts: TurnFacts) -> list[str]:
    norm = _norm(text)
    if _CLAIM.search(norm):
        return ["FORBIDDEN_CLAIM"]
    for sentence in _SENTENCE.split(norm):
        if _RECEIVED.search(sentence) and _ORDER_WORD.search(sentence):
            return ["FORBIDDEN_CLAIM"]
    for match in _WARRANTY_TERM.finditer(norm):
        number = int(match.group(1) or match.group(3))
        unit = (match.group(2) or match.group(4) or "").lower()
        months = number * 12 if unit.startswith(("yil", "йил", "год", "лет", "year")) else number
        if months not in facts.warranty_months:
            return ["FORBIDDEN_CLAIM"]
    if _BARE_GUARANTEE.search(_WARRANTY_TERM.sub(" ", norm)):
        return ["FORBIDDEN_CLAIM"]  # muddatsiz yoki tekshirilmagan "garantiya"
    return []


def validate_reply(text: str, facts: TurnFacts) -> list[str]:
    if not text.strip():
        return ["EMPTY"]
    codes: list[str] = []
    if _DISCOUNT.search(_norm(text)):
        codes.append("DISCOUNT_MENTION")
    codes += _claim_codes(text, facts)
    if any(not _price_ok(a, facts) for a in extract_amounts(_mask_titles(_norm(text), facts))):
        codes.append("PRICE_MISMATCH")
    if any(not _known_product(t, facts) for t in model_tokens(text)):
        codes.append("UNVERIFIED_PRODUCT")
    codes += _stock_codes(text, facts)
    codes += _compat_codes(text, facts)
    return sorted(set(codes))
