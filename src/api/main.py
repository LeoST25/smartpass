"""SmartPass API — FastAPI app com CORS, handler global de exceções e health check.

Entry point: `uvicorn src.api.main:app --reload`

LGPD stateless: zero persistência em disco; todo processamento via BytesIO/UploadFile.
CORS configurável via env CORS_ORIGINS (default localhost:3000,5173 para React/Tailwind).
"""

from __future__ import annotations

import logging
import os
import traceback

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.routes import router

load_dotenv()

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(
    title="SmartPass API",
    description="API REST para cálculo de benefícios de transporte (Vale-Transporte, Vale-Combustível) com integração temporal e análise CLT 6%.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# -----------------------------------------------------------------------------
# CORS
# -----------------------------------------------------------------------------
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
CORS_ORIGINS = [origin.strip() for origin in CORS_ORIGINS if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Exception handlers (sem vazamento de stacktrace)
# -----------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handler para HTTPException — retorna mensagem sem stacktrace."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"sucesso": False, "erro": exc.detail, "tipo": type(exc).__name__},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handler para ValidationError (Pydantic) — retorna detalhes de validação."""
    return JSONResponse(
        status_code=422,
        content={
            "sucesso": False,
            "erro": "Erro de validação nos dados de entrada.",
            "detalhes": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handler global — loga stacktrace mas retorna mensagem genérica sem vazar detalhes."""
    logger.error("Erro não tratado: %s\n%s", exc, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "sucesso": False,
            "erro": "Erro interno do servidor. Tente novamente em instantes.",
            "tipo": "InternalServerError",
        },
    )


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
app.include_router(router)


@app.get("/")
def root():
    """Endpoint raiz — redireciona para docs."""
    return {
        "service": "SmartPass API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
