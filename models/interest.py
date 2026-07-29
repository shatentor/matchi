from pydantic import BaseModel, ConfigDict
from typing import Optional


class Interest(BaseModel):
    """Справочный интерес из таблицы interests.

    id проставляет БД (SERIAL), поэтому у него есть значение по умолчанию:
    в Pydantic v2 Optional без default — обязательное поле, и модель нельзя
    было бы собрать до вставки.
    """
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    slug: str
    title: str
    is_active: bool = True
