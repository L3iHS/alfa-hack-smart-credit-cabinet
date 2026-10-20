from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from app.applications.router import router as applications_router
from app.companies.router import router as companies_router
from app.products.router import router as products_router
from app.auth.router import router as auth_router
from app.auth.schemas import ErrorOutput
from app.auth.service import require_csrf
from app.core.db import get_db

app = FastAPI(
    title="Умный кредитный кабинет", version="0.1.0",
    openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs", redoc_url=None,
    dependencies=[Depends(require_csrf)],
    responses={status: {"model": ErrorOutput} for status in (401, 403, 422, 500, 503)},
)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(companies_router, prefix="/api/v1")
app.include_router(applications_router, prefix="/api/v1")


@app.middleware("http")
async def prevent_private_response_caching(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    content = exc.detail if isinstance(exc.detail, dict) else {
        "code": "http_error", "message": "Запрос не может быть выполнен",
    }
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    fields = {}
    for error in exc.errors():
        name = ".".join(str(part) for part in error["loc"] if part != "body") or "body"
        fields[name] = "Поле не разрешено" if error["type"] == "extra_forbidden" else "Проверьте значение поля"
    return JSONResponse(status_code=422, content={
        "code": "validation_error", "message": "Проверьте введённые данные", "field_errors": fields,
    })


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    return JSONResponse(status_code=503, content={
        "code": "database_unavailable", "message": "Сервис временно недоступен",
    })


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={
        "code": "internal_error", "message": "Не удалось выполнить запрос",
    })


@app.get("/api/v1/health", tags=["Состояние"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
