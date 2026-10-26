"""Short commands for the team planner; the Site enforces author permissions."""
from __future__ import annotations

import html

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import config
from utils.editorial_planner import PlannerError, open_keyboard, planner_request

router = Router()


@router.message(Command("planner"))
async def planner_open(message: Message) -> None:
    await message.answer(
        "<b>Планировщик @podslushano.nl</b>\nЗадачи, идеи и материалы команды — в кабинете.",
        reply_markup=open_keyboard(),
    )


@router.message(Command("planner_post"))
async def planner_post(message: Message) -> None:
    if not message.from_user or message.from_user.id not in config.ADMIN_IDS:
        return
    # Publish in this explicitly selected chat only. Pinning remains manual.
    await message.answer(
        "<b>Рабочий кабинет @podslushano.nl</b>\n\n"
        "Свои задачи, идеи, файлы и сроки смотрим здесь.\n"
        "Новым авторам: сначала откройте приглашение от Алекса.",
        reply_markup=open_keyboard(),
    )


@router.message(Command("planner_link"))
async def planner_link(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    if message.chat.type != "private":
        await message.answer("Код подключения отправьте боту в личные сообщения.")
        return
    code = (command.args or "").strip()
    if not code or len(code) > 200 or any(c.isspace() for c in code):
        await message.answer(
            "В кабинете откройте профиль → «Подключить Telegram».\n"
            "Скопируйте команду /planner_link с кодом и отправьте её сюда."
        )
        return
    try:
        data = await planner_request(
            "bind", code=code, telegramId=message.from_user.id,
            telegramName=message.from_user.full_name,
        )
    except PlannerError as exc:
        await message.answer(str(exc), reply_markup=open_keyboard())
        return
    name = html.escape(str(data.get("name") or message.from_user.full_name))
    await message.answer(
        f"{name}, Telegram подключён.\n"
        "Теперь можно добавлять задачи и идеи:\n"
        "/task Снять открытие в Rotterdam\n"
        "/idea Репортаж с рынка\n"
        "Напоминания включаются в профиле кабинета.",
        reply_markup=open_keyboard(),
    )


async def create_from_command(message: Message, command: CommandObject, kind: str) -> None:
    if not message.from_user:
        return
    raw = (command.args or "").strip()
    examples = {"task": "Снять открытие в Rotterdam", "idea": "Репортаж с рынка", "direction": "Жизнь в Brabant"}
    if not raw:
        await message.answer(
            f"Напишите название после команды:\n/{kind} {examples[kind]}\n"
            "Дополнительные детали можно написать со следующей строки."
        )
        return
    title, _, description = raw.partition("\n")
    if len(title) > 300 or len(description) > 5000:
        await message.answer("Название — до 300 символов, подробности — до 5000.")
        return
    try:
        data = await planner_request(
            "create", telegramId=message.from_user.id, kind=kind,
            title=title.strip(), description=description.strip(),
        )
    except PlannerError as exc:
        await message.answer(str(exc), reply_markup=open_keyboard())
        return
    record = data.get("record") or {}
    label = {"task": "Задача добавлена", "idea": "Идея сохранена", "direction": "Направление добавлено"}[kind]
    await message.answer(
        f"<b>{label}</b>\n{html.escape(str(record.get('title') or title))}",
        reply_markup=open_keyboard(data.get("url")),
    )


@router.message(Command("task"))
async def planner_task(message: Message, command: CommandObject) -> None:
    await create_from_command(message, command, "task")


@router.message(Command("idea"))
async def planner_idea(message: Message, command: CommandObject) -> None:
    await create_from_command(message, command, "idea")


@router.message(Command("direction"))
async def planner_direction(message: Message, command: CommandObject) -> None:
    await create_from_command(message, command, "direction")
