"""JaasError -> HTTP response mapping. Per CONVENTIONS.md, this is the only
place a JaasError's stable `code` gets turned into an HTTP status.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from jaas_registry.common.errors import HTTP_STATUS_BY_CODE, JaasError


async def jaas_error_handler(request: Request, exc: JaasError) -> JSONResponse:
    return JSONResponse(status_code=HTTP_STATUS_BY_CODE[exc.code], content=exc.to_dict())


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(JaasError, jaas_error_handler)
