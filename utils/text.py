import html
from typing import Optional


def escape(text: Optional[str]) -> str:
    """Экранирует текст пользователя для отправки с parse_mode=HTML.

    Без этого описание или имя, содержащее '<' или '&', приводит к
    TelegramBadRequest: can't parse entities.
    """
    if text is None:
        return ""
    return html.escape(str(text), quote=False)
