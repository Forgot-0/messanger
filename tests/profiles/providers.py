from dishka import Provider, Scope, provide

from app.profiles.services.identifier_hasher import IdentifierHasher

TEST_IDENTIFIER_PEPPER = "integration-test-contact-pepper"


class ProfilesIntegrationProvider(Provider):
    """Pepper в тестах фиксирован, чтобы прогон не зависел от .env."""

    @provide(scope=Scope.APP)
    def identifier_hasher(self) -> IdentifierHasher:
        return IdentifierHasher(pepper=TEST_IDENTIFIER_PEPPER)
