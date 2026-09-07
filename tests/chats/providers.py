from dishka import Provider, Scope, provide

from app.chats.config import chat_config
from app.chats.services.livekit_service import LiveKitService
from tests.chats.integration.mock import StubLiveKitService


class ChatsIntegrationProvider(Provider):

        @provide(scope=Scope.REQUEST)
        def livekit_service(self) -> LiveKitService:
            return StubLiveKitService(
                url=chat_config.LIVEKIT_URL,
                api_key="integration-test-key",
                api_secret="integration-test-secret",
            )
