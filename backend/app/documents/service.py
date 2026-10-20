import hashlib
import io
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import PurePosixPath

from fastapi import HTTPException
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications.service import add_event, get_application, require_client
from app.applications.submission_policy import ACCEPTED_CONTENT_TYPES, MAX_FILE_SIZE
from app.auth.models import User
from app.core.config import settings
from app.documents.models import Document


def active_documents(db: Session, application_id: uuid.UUID) -> list[Document]:
    return list(db.scalars(select(Document).where(
        Document.application_id == application_id, Document.deleted_at.is_(None),
    ).order_by(Document.created_at, Document.id)))


def get_document(db: Session, user: User, application_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    get_application(db, user, application_id)
    document = db.scalar(select(Document).where(
        Document.id == document_id, Document.application_id == application_id, Document.deleted_at.is_(None),
    ))
    if document is None:
        raise HTTPException(404, {'code': 'document_not_found', 'message': 'Документ не найден'})
    return document


def require_editable(application, expected_version: int) -> None:
    if application.status != 'draft' or application.version != expected_version:
        raise HTTPException(409, {'code': 'version_conflict', 'message': 'Заявка изменилась, обновите страницу'})


def validate_file(content: bytes, filename: str, content_type: str) -> str:
    if content_type not in ACCEPTED_CONTENT_TYPES:
        raise HTTPException(415, {'code': 'unsupported_media_type', 'message': 'Разрешены только PDF, PNG и JPEG'})
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, {'code': 'file_too_large', 'message': 'Размер файла не должен превышать 10 МБ'})
    filename = PurePosixPath(filename.replace('\\', '/')).name
    filename = ''.join(char for char in filename if char.isprintable()).strip()[:200]
    extensions = {'application/pdf': {'.pdf'}, 'image/png': {'.png'}, 'image/jpeg': {'.jpg', '.jpeg'}}
    try:
        if not content or PurePosixPath(filename).suffix.lower() not in extensions[content_type]:
            raise ValueError('Недопустимое имя или пустой файл')
        if content_type == 'application/pdf':
            if not content.startswith(b'%PDF-'):
                raise ValueError('Не PDF')
            with PdfReader(io.BytesIO(content), strict=True) as reader:
                if reader.is_encrypted or not 1 <= len(reader.pages) <= 1000:
                    raise ValueError('Зашифрованный PDF или недопустимое число страниц')
        else:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if image.format != {'image/png': 'PNG', 'image/jpeg': 'JPEG'}[content_type]:
                        raise ValueError('Формат не соответствует заявленному')
                    image.verify()
                # Проверяем также пиксельные данные, не извлекая текст или финансовые показатели.
                with Image.open(io.BytesIO(content)) as image:
                    image.load()
    except Exception as error:
        raise HTTPException(422, {
            'code': 'invalid_document', 'message': 'Файл повреждён или не соответствует формату',
            'field_errors': {'file': 'Прикрепите корректный PDF, PNG или JPEG без пароля'},
        }) from error
    return filename


def upload_document(db: Session, user: User, application_id: uuid.UUID, expected_version: int,
                    document_type: str, filename: str, content_type: str, content: bytes):
    require_client(user)
    filename = validate_file(content, filename, content_type)
    application = get_application(db, user, application_id, lock=True)
    require_editable(application, expected_version)
    identifier = uuid.uuid4()
    document = Document(
        id=identifier, application_id=application.id, author_id=user.id,
        document_type=document_type, filename=filename, storage_key=str(identifier),
        content_type=content_type, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
    )
    directory = settings.document_storage_path
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / document.storage_key
    commit_started = False
    try:
        with path.open('xb') as handle:
            handle.write(content)
        db.add(document)
        application.version += 1
        application.updated_at = datetime.now(timezone.utc)
        add_event(db, application, user, 'document_uploaded')
        db.flush()
        commit_started = True
        db.commit()
    except Exception:
        # При неизвестном исходе commit сохраняем файл: лишний файл лучше потерянного документа.
        if not commit_started:
            path.unlink(missing_ok=True)
        raise
    return {'document': document, 'application_version': application.version}


def delete_document(db: Session, user: User, application_id: uuid.UUID, document_id: uuid.UUID, expected_version: int):
    require_client(user)
    application = get_application(db, user, application_id, lock=True)
    require_editable(application, expected_version)
    document = get_document(db, user, application_id, document_id)
    document.deleted_at = datetime.now(timezone.utc)
    application.version += 1
    application.updated_at = document.deleted_at
    add_event(db, application, user, 'document_deleted')
    db.commit()
    return {'application_version': application.version}
