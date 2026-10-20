import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.applications.service import get_application, require_client
from app.applications.submission_policy import ACCEPTED_CONTENT_TYPES, MAX_FILE_SIZE
from app.auth.models import User
from app.auth.service import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.documents.schemas import DeletedDocument, DocumentList, UploadedDocument
from app.documents.service import active_documents, delete_document, get_document, upload_document
from app.products.schemas import DocumentType

router = APIRouter(tags=['Документы'])
ExpectedVersion = Annotated[int, Query(ge=1, le=2_147_483_647)]


@router.get('/applications/{application_id}/documents', response_model=DocumentList)
def documents(application_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_application(db, user, application_id)
    return {'items': active_documents(db, application_id)}


@router.post('/applications/{application_id}/documents', response_model=UploadedDocument, status_code=201,
             openapi_extra={'requestBody': {'required': True, 'content': {
                 content_type: {'schema': {'type': 'string', 'format': 'binary'}}
                 for content_type in ACCEPTED_CONTENT_TYPES
             }}})
async def upload(application_id: uuid.UUID, document_type: DocumentType, expected_version: ExpectedVersion,
                 filename: Annotated[str, Query(min_length=1, max_length=255)], request: Request,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_client(user)
    get_application(db, user, application_id)
    content_type = request.headers.get('content-type', '').split(';', 1)[0].lower().strip()
    if content_type not in ACCEPTED_CONTENT_TYPES:
        raise HTTPException(415, {'code': 'unsupported_media_type', 'message': 'Разрешены только PDF, PNG и JPEG'})
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_FILE_SIZE:
            raise HTTPException(413, {'code': 'file_too_large', 'message': 'Размер файла не должен превышать 10 МиБ'})
        content.extend(chunk)
    return await run_in_threadpool(upload_document, db, user, application_id, expected_version,
                                   document_type, filename, content_type, bytes(content))


@router.get('/applications/{application_id}/documents/{document_id}')
def download(application_id: uuid.UUID, document_id: uuid.UUID,
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    document = get_document(db, user, application_id, document_id)
    path = settings.document_storage_path / document.storage_key
    if not path.is_file():
        raise HTTPException(503, {'code': 'document_unavailable', 'message': 'Файл временно недоступен'})
    return FileResponse(path, filename=document.filename, media_type=document.content_type,
                        headers={'X-Content-Type-Options': 'nosniff'})


@router.delete('/applications/{application_id}/documents/{document_id}', response_model=DeletedDocument)
def remove(application_id: uuid.UUID, document_id: uuid.UUID, expected_version: ExpectedVersion,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return delete_document(db, user, application_id, document_id, expected_version)
