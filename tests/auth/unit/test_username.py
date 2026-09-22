import pytest

from app.auth.services.username import (
    BASE_MAX_LENGTH,
    MAX_LENGTH,
    MIN_LENGTH,
    UsernameGenerator,
    normalize_username,
)


class FakeUserRepository:
    def __init__(self, taken: set[str] | None = None) -> None:
        self.taken = taken or set()
        self.checked: list[str] = []

    async def exists_username(self, username: str) -> bool:
        self.checked.append(username)
        return username in self.taken


@pytest.mark.unit
@pytest.mark.auth
class TestNormalizeUsername:

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Forgot-0", "Forgot-0"),
            ("ivan.petrov", "ivan.petrov"),
            ("John O'Brien", "John O'Brien"),
            ("Иван Петров", "Ivan Petrov"),
            ("Женя Щукин", "Zhenya Schukin"),
            ("  spaced   out  ", "spaced out"),
            ("emoji 🎉 name", "emoji name"),
            ("хакер@example.com", "haker example.com"),
        ],
    )
    def test_keeps_a_readable_name(self, raw: str, expected: str) -> None:
        assert normalize_username(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "🎉🎉", "---", "中文"])
    def test_nothing_usable_becomes_empty(self, raw: str | None) -> None:
        assert normalize_username(raw) == ""

    def test_result_fits_the_column_with_room_for_a_suffix(self) -> None:
        assert len(normalize_username("a" * 500)) == BASE_MAX_LENGTH

    @pytest.mark.parametrize(
        "raw",
        ["Иван Петров", "John O'Brien", "Forgot-0", "ivan.petrov"],
    )
    def test_result_matches_the_registration_pattern(self, raw: str) -> None:
        import re

        assert re.fullmatch(r"[a-zA-Z0-9 ,.'-]+", normalize_username(raw))


@pytest.mark.unit
@pytest.mark.auth
class TestUsernameGenerator:

    @staticmethod
    def generator(taken: set[str] | None = None) -> tuple[UsernameGenerator, FakeUserRepository]:
        repository = FakeUserRepository(taken)
        return UsernameGenerator(user_repository=repository), repository  # type: ignore[arg-type]

    async def test_provider_name_is_used_as_is_when_free(self) -> None:
        generator, _ = self.generator()

        assert await generator.generate(
            preferred="Forgot-0", email="dev@example.com"
        ) == "Forgot-0"

    async def test_cyrillic_name_is_transliterated(self) -> None:
        generator, _ = self.generator()

        assert await generator.generate(
            preferred="Иван Петров", email="ivan@example.com"
        ) == "Ivan Petrov"

    async def test_falls_back_to_the_email_local_part(self) -> None:
        generator, _ = self.generator()

        assert await generator.generate(
            preferred=None, email="ivan.petrov@example.com"
        ) == "ivan.petrov"

    async def test_falls_back_to_the_email_when_the_name_is_unusable(self) -> None:
        generator, _ = self.generator()

        assert await generator.generate(
            preferred="🎉🎉", email="ivan.petrov@example.com"
        ) == "ivan.petrov"

    async def test_falls_back_to_a_generic_base_when_nothing_is_usable(self) -> None:
        generator, _ = self.generator()

        username = await generator.generate(preferred=None, email="🎉@example.com")

        assert username.startswith("user")

    async def test_taken_name_gets_a_suffix(self) -> None:
        generator, _ = self.generator(taken={"Forgot-0"})

        username = await generator.generate(preferred="Forgot-0", email="dev@example.com")

        assert username != "Forgot-0"
        assert username.startswith("Forgot-0-")

    async def test_too_short_name_always_gets_a_suffix(self) -> None:
        generator, repository = self.generator()

        username = await generator.generate(preferred="Li", email="li@example.com")

        assert username.startswith("Li-")
        assert len(username) >= MIN_LENGTH
        assert "Li" not in repository.checked

    async def test_result_never_exceeds_the_column(self) -> None:
        generator, _ = self.generator(taken={"a" * BASE_MAX_LENGTH})

        username = await generator.generate(
            preferred="a" * 500, email="a@example.com"
        )

        assert len(username) <= MAX_LENGTH

    async def test_gives_up_on_suffixes_and_still_returns_a_free_name(self) -> None:
        generator, repository = self.generator()
        repository.taken = {"Forgot-0"}

        async def always_taken(username: str) -> bool:
            repository.checked.append(username)
            return True

        repository.exists_username = always_taken  # type: ignore[method-assign]

        username = await generator.generate(preferred="Forgot-0", email="dev@example.com")

        assert username.startswith("Forgot-0-")
        assert len(repository.checked) == generator.attempts + 1
