from urllib.parse import parse_qs, urlparse

from app.core.configs.app import app_config


def api_path(suffix: str) -> str:
    base = app_config.API_V1_STR.rstrip("/")
    tail = suffix.lstrip("/")
    return f"{base}/{tail}" if tail else base


def assert_presigned_url(url: str, *, bucket: str, file_key: str) -> None:

    parsed = urlparse(url)
    assert parsed.scheme in ("http", "https"), url
    assert parsed.path.startswith(f"/{bucket}/"), parsed.path
    assert parsed.path.endswith(file_key.rsplit("/", 1)[-1]), parsed.path

    query = parse_qs(parsed.query)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Signature"], "ссылка обязана быть подписана"
    assert int(query["X-Amz-Expires"][0]) > 0
