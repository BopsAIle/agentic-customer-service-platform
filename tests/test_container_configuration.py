from pathlib import Path

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).parents[1]


def test_backend_runtime_is_minimal_non_root_and_sigterm_aware() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    runtime = dockerfile.split(" AS runtime", maxsplit=1)[1]

    assert " AS builder" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert "USER app" in runtime
    assert "STOPSIGNAL SIGTERM" in runtime
    assert "--timeout-graceful-shutdown" in runtime
    assert "COPY --from=uv" not in runtime
    assert "uv sync" not in runtime


def test_compose_uses_readiness_and_production_resource_boundaries() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    production = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text())
    backend_healthcheck = " ".join(compose["services"]["backend"]["healthcheck"]["test"])
    backend = production["services"]["backend"]
    frontend = production["services"]["frontend"]

    assert "/ready" in backend_healthcheck
    assert compose["services"]["frontend"]["depends_on"]["backend"]["condition"] == (
        "service_healthy"
    )
    assert backend["restart"] == "unless-stopped"
    assert backend["read_only"] is True
    assert backend["cap_drop"] == ["ALL"]
    assert backend["deploy"]["resources"]["limits"]
    assert frontend["read_only"] is True
    assert frontend["deploy"]["resources"]["limits"]


def test_frontend_config_applies_security_and_cache_boundaries() -> None:
    nginx = (ROOT / "frontend" / "nginx.conf").read_text()
    headers = (ROOT / "frontend" / "security-headers.conf").read_text()

    assert "Content-Security-Policy" in headers
    assert "X-Content-Type-Options" in headers
    assert "location /assets/" in nginx
    assert "max-age=31536000, immutable" in nginx
    assert 'Cache-Control "no-cache"' in nginx
    assert "try_files $uri $uri/ /index.html" in nginx
    assert "server_tokens off" in nginx
