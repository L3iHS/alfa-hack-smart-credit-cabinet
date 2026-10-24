from pydantic import ValidationError

from app.assistant.provider import AssistantUnavailable
from app.assistant.schemas import GeneratedAnswer, Source


def validate_answer(raw: dict, sources: list[Source]) -> tuple[GeneratedAnswer, list[Source]]:
    try:
        generated = GeneratedAnswer.model_validate(raw)
        allowed = {source.id: source for source in sources}
        if any(identifier not in allowed for identifier in generated.source_ids):
            raise ValueError('Неизвестный источник')
    except (ValidationError, ValueError, TypeError):
        raise AssistantUnavailable() from None
    return generated, [allowed[key] for key in dict.fromkeys(generated.source_ids)]
