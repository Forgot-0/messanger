from starlette.requests import Request
from starlette.websockets import WebSocket


def get_ip_from_request(request: Request | WebSocket) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0]
    else:
        if request.client is None:
            raise RuntimeError("Request client is unavailable")

        ip = request.client.host
    return ip


def get_ws_access_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token") or websocket.query_params.get("access_token")
    if token:
        return token

    authorization = websocket.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()

    protocols = websocket.headers.get("sec-websocket-protocol", "")
    for part in (p.strip() for p in protocols.split(",")):
        lower = part.lower()
        if lower.startswith("bearer."):
            return part.split(".", 1)[1]
        if lower.startswith("bearer "):
            return part.split(" ", 1)[1]
    return None


