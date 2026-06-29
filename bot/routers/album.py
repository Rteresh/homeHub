from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup
from asgiref.sync import sync_to_async

from apps.accounts.models import TelegramProfile
from apps.files.albums import AlbumService
from apps.files.models import Album

router = Router()

ALBUM_BUTTON = "Альбом"
HELP_BUTTON = "Help"
NO_ALBUM_BUTTON = "Без альбома"
SELECT_ALBUM_BUTTON = "Выбрать альбом"
CREATE_ALBUM_BUTTON = "Создать альбом"
BACK_TO_MAIN_BUTTON = "Назад"
SHUTDOWN_BUTTON = "Выключить сервер"


class CreateAlbumStates(StatesGroup):
    """FSM-состояние ожидания названия нового альбома от пользователя."""

    waiting_name = State()


def main_keyboard(*, is_bot_admin: bool = False) -> ReplyKeyboardMarkup:
    """Создаёт постоянную клавиатуру Telegram с быстрым доступом к словарю, альбомам и справке."""
    rows = [
        [KeyboardButton(text="Словарь"), KeyboardButton(text=ALBUM_BUTTON)],
        [KeyboardButton(text=HELP_BUTTON)],
    ]
    if is_bot_admin:
        rows.append([KeyboardButton(text=SHUTDOWN_BUTTON)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def album_menu_keyboard() -> ReplyKeyboardMarkup:
    """Показывает подменю выбора режима загрузки: без альбома, выбор или создание."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=NO_ALBUM_BUTTON), KeyboardButton(text=SELECT_ALBUM_BUTTON)],
            [KeyboardButton(text=CREATE_ALBUM_BUTTON), KeyboardButton(text=BACK_TO_MAIN_BUTTON)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие с альбомом",
    )


def format_active_album_label(profile: TelegramProfile, user) -> str:
    """Возвращает текст текущего активного альбома для сообщений бота."""
    if profile.active_album_id is None:
        return "Загрузки без альбома."
    label = AlbumService.format_album_label(profile.active_album, user)
    return f"Активный альбом: «{label}»."


@router.message(F.text.casefold() == ALBUM_BUTTON.casefold())
async def album_menu(message: Message, telegram_profile: TelegramProfile, django_user) -> None:
    """Открывает подменю альбомов и показывает текущий режим загрузки."""
    profile = await sync_to_async(
        lambda: TelegramProfile.objects.select_related(
            "active_album",
            "active_album__owner",
            "active_album__owner__telegram_profile",
        ).get(pk=telegram_profile.pk)
    )()
    await message.answer(
        f"{format_active_album_label(profile, django_user)}\nВыберите действие:",
        reply_markup=album_menu_keyboard(),
    )


@router.message(F.text.casefold() == BACK_TO_MAIN_BUTTON.casefold())
async def back_to_main(message: Message, telegram_profile: TelegramProfile) -> None:
    """Возвращает пользователя к основной клавиатуре бота."""
    await message.answer(
        "Главное меню.",
        reply_markup=main_keyboard(is_bot_admin=telegram_profile.is_bot_admin),
    )


@router.message(F.text.casefold() == NO_ALBUM_BUTTON.casefold())
async def disable_album(message: Message, telegram_profile: TelegramProfile, state: FSMContext) -> None:
    """Сбрасывает активный альбом: новые файлы сохраняются без привязки к альбому."""
    await state.clear()
    await sync_to_async(AlbumService.set_active_album)(telegram_profile, None)
    await message.answer(
        "Загрузки без альбома. Новые файлы не будут добавляться в альбом.",
        reply_markup=album_menu_keyboard(),
    )


@router.message(F.text.casefold() == SELECT_ALBUM_BUTTON.casefold())
async def choose_album_prompt(message: Message, django_user) -> None:
    """Показывает inline-список альбомов пользователя для выбора активного."""
    albums = await sync_to_async(
        lambda: list(
            AlbumService.list_for_user(django_user).select_related("owner", "owner__telegram_profile")
        )
    )()
    if not albums:
        await message.answer(
            "Пока нет доступных альбомов. Нажмите «Создать альбом» и введите название.",
            reply_markup=album_menu_keyboard(),
        )
        return

    await message.answer(
        "Выберите альбом для загрузок (доступны альбомы всех пользователей HomeHub):",
        reply_markup=album_select_keyboard(albums, django_user),
    )


@router.message(F.text.casefold() == CREATE_ALBUM_BUTTON.casefold())
async def create_album_prompt(message: Message, state: FSMContext) -> None:
    """Просит пользователя ввести название нового альбома."""
    await state.set_state(CreateAlbumStates.waiting_name)
    await message.answer(
        "Введите название нового альбома:",
        reply_markup=album_menu_keyboard(),
    )


@router.message(CreateAlbumStates.waiting_name, F.text)
async def create_album_from_name(
    message: Message,
    django_user,
    telegram_profile: TelegramProfile,
    state: FSMContext,
) -> None:
    """Создаёт альбом по введённому названию и делает его активным для загрузок."""
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым. Введите название альбома:")
        return

    if name.casefold() in {
        NO_ALBUM_BUTTON.casefold(),
        SELECT_ALBUM_BUTTON.casefold(),
        CREATE_ALBUM_BUTTON.casefold(),
        BACK_TO_MAIN_BUTTON.casefold(),
        ALBUM_BUTTON.casefold(),
        SHUTDOWN_BUTTON.casefold(),
        "словарь",
    }:
        await message.answer("Введите название альбома текстом, а не кнопкой меню:")
        return

    try:
        album = await sync_to_async(AlbumService.create_album)(django_user, name)
        await sync_to_async(AlbumService.set_active_album)(telegram_profile, album)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await state.clear()
    await message.answer(
        f"Альбом «{album.name}» создан и выбран. Новые файлы будут добавляться в него.",
        reply_markup=album_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("album:select:"))
async def select_album_callback(
    callback: CallbackQuery,
    django_user,
    telegram_profile: TelegramProfile,
    state: FSMContext,
) -> None:
    """Обрабатывает выбор альбома из inline-клавиатуры и сохраняет его как активный."""
    public_id = callback.data.removeprefix("album:select:")
    album = await sync_to_async(AlbumService.get_for_user)(django_user, public_id)
    if album is None:
        await callback.answer("Альбом не найден.", show_alert=True)
        return

    await state.clear()
    await sync_to_async(AlbumService.set_active_album)(telegram_profile, album)
    await callback.answer(f"Выбран альбом «{AlbumService.format_album_label(album, django_user)}»")
    if callback.message:
        await callback.message.answer(
            f"Активный альбом: «{AlbumService.format_album_label(album, django_user)}». Новые файлы будут добавляться в него.",
            reply_markup=album_menu_keyboard(),
        )


def album_select_keyboard(albums: list[Album], user) -> InlineKeyboardMarkup:
    """Строит inline-клавиатуру со списком доступных альбомов пользователя."""
    rows = [
        [
            InlineKeyboardButton(
                text=AlbumService.format_album_label(album, user),
                callback_data=f"album:select:{album.public_id}",
            )
        ]
        for album in albums
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
