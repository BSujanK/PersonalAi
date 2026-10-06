"""Unhandled request exceptions and uvicorn errors reach agent.log without any content."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from agent import main as main_module
from agent.api.errors import ErrorLog

SECRET = "secret body me@example.com"


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ErrorLog)

    @app.get("/boom/{item}")
    def boom(item: str) -> None:
        raise RuntimeError(SECRET)

    @app.get("/down")
    def down() -> JSONResponse:
        return JSONResponse({"detail": "down"}, status_code=503)

    @app.get("/missing")
    def missing() -> None:
        raise HTTPException(status_code=404, detail="nope")

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/stream")
    def stream() -> StreamingResponse:
        def chunks() -> Iterator[bytes]:
            yield b"first"
            raise ValueError(SECRET)

        return StreamingResponse(chunks())

    return app


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "agent.api"]


def test_an_unhandled_exception_is_logged_by_route_template_and_answers_500(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.INFO):
        response = client.get("/boom/user-private-7?token=abc")
    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    (record,) = _records(caplog)
    assert record.levelno == logging.ERROR
    assert record.getMessage() == (
        "request failed: method=GET route=/boom/{item} status=500 exc=RuntimeError"
    )
    assert record.exc_info is None
    for leaked in ("secret", "me@example.com", "user-private-7", "token", "abc"):
        assert leaked not in record.getMessage()


def test_a_5xx_response_without_an_exception_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_app())
    with caplog.at_level(logging.INFO):
        assert client.get("/down").status_code == 503
    (record,) = _records(caplog)
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "request failed: method=GET route=/down status=503 exc=none"


def test_client_errors_and_successes_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_app())
    with caplog.at_level(logging.DEBUG):
        assert client.get("/missing").status_code == 404
        assert client.get("/nowhere").status_code == 404
        assert client.get("/ok").status_code == 200
    assert _records(caplog) == []


def test_an_exception_after_the_response_started_is_logged_and_re_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_app(), raise_server_exceptions=True)
    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        client.get("/stream")
    (record,) = _records(caplog)
    assert record.getMessage() == (
        "request failed: method=GET route=/stream status=200 exc=ValueError"
    )
    assert "secret" not in record.getMessage()


@pytest.fixture
def clean_loggers() -> Iterator[None]:
    names = ("agent", "uvicorn.error")
    saved = {
        name: (
            list(logging.getLogger(name).handlers),
            list(logging.getLogger(name).filters),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in names
    }
    for name in names:
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).filters[:] = []
        logging.getLogger(name).propagate = True
    yield
    for name, (handlers, filters, level, propagate) in saved.items():
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = handlers
        logger.filters[:] = filters
        logger.setLevel(level)
        logger.propagate = propagate


def _flush(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()


def test_uvicorn_errors_reach_agent_log_without_a_traceback(
    tmp_path: Path, clean_loggers: None
) -> None:
    settings = main_module.Settings.from_env({"PERSONALAI_DB_PATH": str(tmp_path / "agent.db")})
    main_module._configure_logging(settings)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    try:
        raise RuntimeError(SECRET)
    except RuntimeError:
        uvicorn_logger.error("Exception in ASGI application", exc_info=True)
    uvicorn_logger.info("below the warning level")
    _flush(uvicorn_logger)
    text = (tmp_path / "agent.log").read_text(encoding="utf-8")
    assert "uvicorn.error Exception in ASGI application (RuntimeError)" in text
    assert "Traceback" not in text and "File " not in text
    assert "secret" not in text and "me@example.com" not in text
    assert "below the warning level" not in text


def test_configuring_logging_twice_adds_no_duplicate_handlers(
    tmp_path: Path, clean_loggers: None
) -> None:
    settings = main_module.Settings.from_env({"PERSONALAI_DB_PATH": str(tmp_path / "agent.db")})
    uvicorn_logger = logging.getLogger("uvicorn.error")
    main_module._configure_logging(settings)
    first = list(uvicorn_logger.handlers)
    assert len(first) == 2  # stderr and agent.log, the agent logger's own
    main_module._configure_logging(settings)
    assert uvicorn_logger.handlers == first
    assert sum(isinstance(f, main_module._NoTraceback) for f in uvicorn_logger.filters) == 1
    uvicorn_logger.error("once")
    _flush(uvicorn_logger)
    assert (tmp_path / "agent.log").read_text(encoding="utf-8").count("once") == 1
