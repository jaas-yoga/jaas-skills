"""RuneError -> HTTP response mapping. Per CONVENTIONS.md, this is the only
place a RuneError's stable `code` gets turned into an HTTP status.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rune_registry.common.errors import HTTP_STATUS_BY_CODE, RuneError


async def rune_error_handler(request: Request, exc: RuneError) -> JSONResponse:
    return JSONResponse(status_code=HTTP_STATUS_BY_CODE[exc.code], content=exc.to_dict())


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RuneError, rune_error_handler)
