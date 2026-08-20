"""Access log middleware, exercised through a real ASGI app."""
from __future__ import annotations

import logging

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from fabric_api_mcp.middleware import access_log as al
from fabric_api_mcp.middleware.access_log import AccessLogMiddleware


def build_client(*, boom=False):
    async def endpoint(request):
        if boom:
            raise RuntimeError("kaboom")
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/thing", endpoint, methods=["GET"])])
    app.add_middleware(AccessLogMiddleware)
    return TestClient(app, raise_server_exceptions=True)


class TestRequestId:
    def test_generated_when_absent(self):
        response = build_client().get("/thing")
        assert response.status_code == 200
        rid = response.headers["x-request-id"]
        assert len(rid) == 12  # uuid4().hex[:12]

    def test_incoming_header_is_propagated(self):
        # Distributed tracing: the caller's id must survive, not be replaced.
        response = build_client().get("/thing", headers={"x-request-id": "trace-me-123"})
        assert response.headers["x-request-id"] == "trace-me-123"


class TestLogging:
    def test_logs_method_path_and_status(self, caplog):
        with caplog.at_level(logging.INFO, logger="fabric.mcp"):
            build_client().get("/thing")
        messages = [r.getMessage() for r in caplog.records if r.name == "fabric.mcp"]
        assert any("HTTP GET /thing -> 200" in m for m in messages)

    def test_attaches_structured_extra_fields(self, caplog):
        with caplog.at_level(logging.INFO, logger="fabric.mcp"):
            build_client().get("/thing")
        record = next(
            r for r in caplog.records
            if r.name == "fabric.mcp" and "HTTP GET" in r.getMessage()
        )
        # These field names are what the JSON formatter and dashboards consume.
        for field in ("request_id", "path", "method", "status", "duration_ms", "client_ip"):
            assert hasattr(record, field), f"missing extra field: {field}"
        assert record.status == 200
        assert record.path == "/thing"

    def test_unauthenticated_requests_log_as_anonymous(self, caplog):
        with caplog.at_level(logging.INFO, logger="fabric.mcp"):
            build_client().get("/thing")
        messages = [r.getMessage() for r in caplog.records if r.name == "fabric.mcp"]
        assert any("user=anonymous" in m for m in messages)

    def test_can_be_silenced_by_config(self, caplog, monkeypatch):
        monkeypatch.setattr(al.config, "uvicorn_access_log", False)
        with caplog.at_level(logging.INFO, logger="fabric.mcp"):
            response = build_client().get("/thing")
        messages = [r.getMessage() for r in caplog.records if r.name == "fabric.mcp"]
        assert not any("HTTP GET" in m for m in messages)
        # Silencing the log must not stop the tracing header being set.
        assert "x-request-id" in response.headers


class TestExceptions:
    def test_exception_is_logged_and_re_raised(self, caplog):
        with caplog.at_level(logging.INFO, logger="fabric.mcp"):
            with pytest.raises(RuntimeError, match="kaboom"):
                build_client(boom=True).get("/thing")

        records = [r for r in caplog.records if r.name == "fabric.mcp"]
        assert any(r.levelno == logging.ERROR for r in records), "no ERROR record"
        assert any("Unhandled exception during request" in r.getMessage() for r in records)

    def test_failed_request_is_logged_as_500(self, caplog):
        with caplog.at_level(logging.INFO, logger="fabric.mcp"):
            with pytest.raises(RuntimeError):
                build_client(boom=True).get("/thing")
        messages = [r.getMessage() for r in caplog.records if r.name == "fabric.mcp"]
        assert any("-> 500" in m for m in messages)

    def test_exception_record_carries_a_traceback(self, caplog):
        with caplog.at_level(logging.INFO, logger="fabric.mcp"):
            with pytest.raises(RuntimeError):
                build_client(boom=True).get("/thing")
        record = next(
            r for r in caplog.records
            if "Unhandled exception during request" in r.getMessage()
        )
        assert record.exc_info is not None
