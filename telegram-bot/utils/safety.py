"""Защита LLM-pipeline от prompt injection и cost runaway.

Используется handlers перед отправкой пользовательского ввода в Gemini.
- MAX_INPUT_LENGTHS: жёсткие потолки длины по типу запроса.
- detect_injection(): простой keyword-фильтр от script-kiddie атак типа
  «ignore previous», «забудь предыдущие инструкции».
- sanitize_input(): нормализует whitespace, обрезает по лимиту, возвращает
  (clean_text, was_truncated).
"""
import re
import logging

logger = logging.getLogger(__name__)


# Жёсткие лимиты на длину сообщения от юзера перед отправкой в LLM.
# Подобраны с запасом: «потратил 8000 на ужин с друзьями в Italian House» — ~50 симв,
# 300 хватит даже на длинные описания. AI-вопрос 500 — длинных query очень мало,
# но иногда юзер описывает контекст («сравни мае и апрель ...») — 500 ок.
MAX_INPUT_LENGTHS = {
    "transaction": 300,   # «потратил 250 на обед»
    "advisor":     500,   # /ask: «где я слил больше всего за неделю?»
    "voice":       2000,  # транскрипция голосового — длиннее
    "description": 200,   # описание категории, регулярного и т.п.
}


# Известные injection-паттерны (русский + английский). Список не панацея —
# обходится перефразированием, но фиксит >80% наивных атак и даёт сигнал в логи.
# Регулярки case-insensitive, multi-word фразы matched как substring.
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above|prior|earlier)\s+(instructions?|prompts?|rules?)",
    r"forget\s+(all\s+)?(previous|above|prior|earlier)\s+(instructions?|prompts?|rules?|context)",
    r"disregard\s+(all\s+)?(previous|above|prior)\s+",
    r"\byou\s+are\s+now\b",
    r"\bact\s+as\b",
    r"\bsystem\s+prompt\b",
    r"\bnew\s+instructions?:?",
    r"забудь\s+(все\s+)?(предыдущ|выше|ранее)",
    r"игнорир(уй|овать)\s+(все\s+)?(предыдущ|выше|ранее)",
    r"пренебреги\s+",
    r"теперь\s+ты\s+",
    r"\bновые?\s+инструкци",
    r"\bсистемн(ый|ой)\s+промпт",
    r"\bраскрой\s+(свой|твой)\s+промпт",
    r"\bвыведи\s+(свой|твой|весь)\s+(промпт|system)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def detect_injection(text: str) -> str | None:
    """Возвращает matched-фрагмент если найдена попытка injection, иначе None."""
    if not text:
        return None
    m = _INJECTION_RE.search(text)
    return m.group(0) if m else None


def sanitize_input(text: str, kind: str) -> tuple[str, bool]:
    """Нормализует whitespace и обрезает текст до MAX_INPUT_LENGTHS[kind].
    Возвращает (clean_text, was_truncated). Неизвестный kind → лимит 500 по умолчанию."""
    if not text:
        return "", False
    # Убираем zero-width и control-символы (часто используются в скрытых injection).
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    cap = MAX_INPUT_LENGTHS.get(kind, 500)
    if len(cleaned) > cap:
        return cleaned[:cap], True
    return cleaned, False
