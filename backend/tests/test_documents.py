import struct
import zlib
from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import text

from test_application_drafts import BASE, authenticate, create


def png_bytes():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00'))
        + chunk(b'IEND', b'')
    )


def upload(client, headers, draft, document_type='financial_statement', content=None, filename='Сведения.png', mime='image/png'):
    return client.post(
        f"{BASE}/{draft['id']}/documents",
        params={'document_type': document_type, 'expected_version': draft['version'], 'filename': filename},
        content=png_bytes() if content is None else content,
        headers={**headers, 'Content-Type': mime},
    )


def attach(client, headers, draft, document_type='financial_statement'):
    response = upload(client, headers, draft, document_type)
    assert response.status_code == 201, response.text
    draft = {**draft, 'version': response.json()['application_version']}
    return draft, response.json()['document']


def test_document_roundtrip_versions_and_access(client):
    headers = authenticate(client)
    original = create(client, headers)
    draft, document = attach(client, headers, original)
    assert draft['version'] == original['version'] + 1
    assert document['filename'] == 'Сведения.png'
    assert document['size_bytes'] == len(png_bytes())
    assert 'storage_key' not in document
    path = f"{BASE}/{draft['id']}/documents"
    assert client.get(path).json()['items'] == [document]
    downloaded = client.get(f"{path}/{document['id']}")
    assert downloaded.content == png_bytes()
    assert downloaded.headers['content-type'] == 'image/png'
    assert downloaded.headers['content-disposition'].startswith('attachment;')
    assert downloaded.headers['x-content-type-options'] == 'nosniff'
    assert upload(client, headers, original).status_code == 409
    for email in ('client2@example.test', 'staff@example.test'):
        other_headers = authenticate(client, email)
        assert client.get(path).status_code == 404
        assert client.get(f"{path}/{document['id']}").status_code == 404
        assert client.delete(f"{path}/{document['id']}", params={'expected_version': draft['version']}, headers=other_headers).status_code in (403, 404)
    headers = authenticate(client)
    assert client.delete(f"{path}/{document['id']}", params={'expected_version': original['version']}, headers=headers).status_code == 409
    deleted = client.delete(f"{path}/{document['id']}", params={'expected_version': draft['version']}, headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()['application_version'] == draft['version'] + 1
    assert client.get(path).json()['items'] == []
    assert client.get(f"{path}/{document['id']}").status_code == 404
    assert [event['event_type'] for event in client.get(f"{BASE}/{draft['id']}/history").json()['items']] == [
        'draft_created', 'document_uploaded', 'document_deleted',
    ]


@pytest.mark.parametrize('content,filename,mime,status', [
    (b'', 'empty.png', 'image/png', 422),
    (b'not a picture', 'fake.png', 'image/png', 422),
    (b'%PDF-1.4\nbroken\n%%EOF', 'broken.pdf', 'application/pdf', 422),
    (png_bytes(), 'wrong.pdf', 'application/pdf', 422),
    (png_bytes(), 'wrong.txt', 'image/png', 422),
    (png_bytes(), 'file.png', 'text/html', 415),
    (b'a' * (10 * 1024 * 1024 + 1), 'large.pdf', 'application/pdf', 413),
])
def test_reject_invalid_documents_without_changes(client, content, filename, mime, status):
    headers = authenticate(client)
    draft = create(client, headers)
    response = upload(client, headers, draft, content=content, filename=filename, mime=mime)
    assert response.status_code == status, response.text
    assert client.get(f"{BASE}/{draft['id']}").json()['version'] == draft['version']
    assert client.get(f"{BASE}/{draft['id']}/documents").json()['items'] == []


def test_upload_filename_is_not_storage_path(client, db):
    headers = authenticate(client)
    draft = create(client, headers)
    response = upload(client, headers, draft, filename='../../outside.png')
    assert response.status_code == 201
    document = response.json()['document']
    assert document['filename'] == 'outside.png'
    key = db.execute(text('SELECT storage_key FROM documents WHERE id=:id'), {'id': document['id']}).scalar_one()
    assert '/' not in key and '..' not in key


def test_document_requires_csrf_and_ownership(client):
    headers = authenticate(client)
    draft = create(client, headers)
    assert upload(client, {}, draft).status_code == 403
    foreign = authenticate(client, 'client2@example.test')
    assert upload(client, foreign, draft).status_code == 404


@pytest.mark.parametrize('format,mime,extension', [('JPEG', 'image/jpeg', 'jpg'), ('PDF', 'application/pdf', 'pdf')])
def test_supported_document_formats(client, format, mime, extension):
    stream = BytesIO()
    if format == 'PDF':
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(stream)
    else:
        Image.new('RGB', (2, 2)).save(stream, format=format)
    headers = authenticate(client)
    draft = create(client, headers)
    response = upload(client, headers, draft, content=stream.getvalue(), filename=f'Файл.{extension}', mime=mime)
    assert response.status_code == 201, response.text
    assert client.get(f"{BASE}/{draft['id']}/documents/{response.json()['document']['id']}").content == stream.getvalue()


def test_exact_size_limit_is_allowed(client):
    # Дополнительный PNG-блок увеличивает файл до границы без повреждения изображения.
    original = png_bytes()
    padding = b'x' * (10 * 1024 * 1024 - len(original) - 12)
    kind = b'tEXt'
    extra = struct.pack('>I', len(padding)) + kind + padding + struct.pack('>I', zlib.crc32(kind + padding))
    content = original[:-12] + extra + original[-12:]
    headers = authenticate(client)
    draft = create(client, headers)
    response = upload(client, headers, draft, content=content)
    assert response.status_code == 201, response.text


def test_upload_rolls_back_file_and_metadata_before_commit(client, db, monkeypatch):
    from app.core.config import settings
    from app.documents import service

    headers = authenticate(client)
    draft = create(client, headers)

    def fail_event(*args, **kwargs):
        raise RuntimeError('Искусственный сбой до commit')

    monkeypatch.setattr(service, 'add_event', fail_event)
    assert upload(client, headers, draft).status_code == 500
    assert list(settings.document_storage_path.iterdir()) == []
    assert client.get(f"{BASE}/{draft['id']}").json()['version'] == draft['version']
    assert db.execute(text('SELECT count(*) FROM documents')).scalar_one() == 0
