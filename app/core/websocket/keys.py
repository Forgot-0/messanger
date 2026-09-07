class WebsocketKeys:
    _NAMESPACE = "ws:v1:"

    @staticmethod
    def presence_last_seen_zset() -> str:
        return f"{WebsocketKeys._NAMESPACE}presence:last_seen"

    @staticmethod
    def user_route_key(user_id: int) -> str:
        return f"ws:route:user:{int(user_id)}"

    @staticmethod
    def gateway_route_key(gateway_id: str) -> str:
        return f"ws:route:gateway:{gateway_id}"

    @staticmethod
    def connection_key(connection_id: str) -> str:
        return f"ws:conn:{connection_id}"

    @staticmethod
    def gateway_stream_key(gateway_id: str) -> str:
        return f"ws:gateway:{gateway_id}:stream"

    @staticmethod
    def active_subscription_key(channel: str) -> str:
        return f"ws:sub:chat:{channel}"

    @staticmethod
    def connection_subscription_key(connection_id: str, channel: str) -> str:
        return f"ws:sub:conn:{connection_id}:{channel}"

    @staticmethod
    def active_subscription_route(user_id: int, gateway_id: str, connection_id: str) -> str:
        return f"{int(user_id)}:{gateway_id}:{connection_id}"
