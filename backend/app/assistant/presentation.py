import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.assistant.schemas import Source


def _decimal_text(value: Decimal, *, grouping: bool = False) -> str:
    rounded = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    number = format(rounded, ',.2f' if grouping else '.2f')
    integer, fractional = number.rsplit('.', 1)
    integer = integer.replace(',', ' ')
    return integer if fractional == '00' else f'{integer},{fractional}'


def _presentation_data(value):
    if isinstance(value, list):
        return [_presentation_data(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        suffix = '_kopecks' if key.endswith('_kopecks') else '_bps' if key.endswith('_bps') else None
        if suffix:
            shown_key = key[:-len(suffix)] + ('_rubles' if suffix == '_kopecks' else '_percent')
            if item is None:
                result[shown_key] = None
            else:
                try:
                    number = Decimal(str(item)) / 100
                    if not number.is_finite():
                        raise InvalidOperation
                    result[shown_key] = _decimal_text(number, grouping=suffix == '_kopecks') + (' ₽' if suffix == '_kopecks' else '%')
                except (InvalidOperation, ValueError):
                    # Не подменяем отсутствующие или некорректные сведения нулём.
                    result[shown_key] = 'Некорректное значение в источнике'
        else:
            result[key] = _presentation_data(item)
    return result


def prompt_sources(sources: list[Source]) -> list[dict]:
    """Готовит читаемые суммы для модели, сохраняя исходные источники API без изменений."""
    result = []
    for source in sources:
        shown = source.model_dump()
        try:
            data = json.loads(source.text)
        except (ValueError, TypeError):
            pass
        else:
            shown['text'] = json.dumps(_presentation_data(data), ensure_ascii=False)
        result.append(shown)
    return result
