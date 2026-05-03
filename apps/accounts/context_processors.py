def account_display_name(request) -> dict[str, str]:
    """Возвращает имя текущего пользователя для верхней навигации: Telegram-имя при наличии или Django username."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"account_display_name": ""}

    profile = getattr(user, "telegram_profile", None)
    if profile:
        return {"account_display_name": profile.display_name}
    return {"account_display_name": user.get_username()}
