"""Хендлеры верификации владения ботом для внешних каталогов/площадок.

Каталоги типа appss.pro / apps.center и т.п. перед публикацией просят
доказать что мы реально владельцы бота — обычно командой, на которую бот
должен ответить строго определённой строкой. Это безопасный паттерн:
им не нужен ни BOT_TOKEN, ни админ-доступ.

Команды складываем в этот модуль, чтобы не засорять основные хендлеры
и иметь одно место для всех «верификаций».
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("appss_verify"))
async def cmd_appss_verify(message: Message):
    """Подтверждение владения @smartcash_ai_bot для каталога appss.pro.
    Бот должен ответить ровно строкой `appss_e920c2` — платформа парсит ответ
    и засчитывает листинг. Команда видима любому юзеру (специально), потому
    что верифицирующий бот appss.pro дёргает её со своего account."""
    await message.answer("appss_e920c2")
