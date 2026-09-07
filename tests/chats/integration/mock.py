from dataclasses import dataclass

from app.chats.services.livekit_service import LiveKitService


@dataclass
class StubLiveKitService(LiveKitService):
    async def create_room(
        self,
        slug: str,
        max_participants: int | None = None,
        metadata: str = "",
    ) -> None:
        return None

    async def delete_room(self, slug: str) -> None:
        return None

    def generate_join_token(
        self,
        slug: str,
        user_id: str,
        username: str,
        can_publish: bool = True,
        can_subscribe: bool = True,
        can_publish_data: bool = True,
        room_admin: bool = False,
    ) -> str:
        return "integration-test-livekit-jwt"

    async def mute_participant(self, slug: str, identity: str, muted: bool = True) -> None:
        return None
