import pytest

from app.auth.config import auth_config
from app.auth.exceptions import InvalidUsernameError
from app.auth.models.user import ChangedUsernameEvent, User


def make_user(username: str = "old_name") -> User:
    return User(id=7, email="user@example.com", username=username)


@pytest.mark.unit
@pytest.mark.auth
class TestUsernameRules:

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("ivan_petrov", "ivan_petrov"),
            ("Durov", "Durov"),
            ("@durov", "durov"),
            ("  spaced  ", "spaced"),
            ("a1b2c", "a1b2c"),
            ("x" * auth_config.USERNAME_MAX_LENGTH, "x" * auth_config.USERNAME_MAX_LENGTH),
        ],
    )
    def test_valid_name_is_cleaned(self, raw: str, expected: str) -> None:
        assert User.validate_username(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["abcd", "@abcd", "x" * (auth_config.USERNAME_MAX_LENGTH + 1), ""],
    )
    def test_length_is_enforced(self, raw: str) -> None:
        with pytest.raises(InvalidUsernameError) as exc_info:
            User.validate_username(raw)

        assert exc_info.value.reason == "length"

    @pytest.mark.parametrize(
        "raw",
        [
            "1ivan",          # начинается с цифры
            "_ivan",          # начинается с подчёркивания
            "ivan_",          # кончается подчёркиванием
            "ivan petrov",    # пробел
            "ivan.petrov",    # точка
            "ivan-petrov",    # дефис
            "иван_петров",    # не латиница
            "ivan🎉ok",
        ],
    )
    def test_format_is_enforced(self, raw: str) -> None:
        with pytest.raises(InvalidUsernameError) as exc_info:
            User.validate_username(raw)

        assert exc_info.value.reason == "format"

    @pytest.mark.parametrize("raw", ["admin", "Admin", "SUPPORT", "@telegram"])
    def test_reserved_names_are_refused_in_any_case(self, raw: str) -> None:
        with pytest.raises(InvalidUsernameError) as exc_info:
            User.validate_username(raw)

        assert exc_info.value.reason == "reserved"
        assert exc_info.value.code == "INVALID_USERNAME"
        assert exc_info.value.detail == {"username": raw, "reason": "reserved"}


@pytest.mark.unit
@pytest.mark.auth
class TestChangeUsername:

    def test_change_registers_an_event_with_both_names(self) -> None:
        user = make_user("old_name")

        user.change_username("@New_Name")

        assert user.username == "New_Name"
        events = user.pull_events()
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, ChangedUsernameEvent)
        assert event.get_name() == "auth.user.username_changed"
        assert event.get_partition_key() == "7"
        assert (event.user_id, event.old_username, event.username) == (7, "old_name", "New_Name")

    def test_same_name_changes_nothing(self) -> None:
        user = make_user("same_name")

        user.change_username("same_name")

        assert user.pull_events() == []

    def test_invalid_name_leaves_the_user_untouched(self) -> None:
        user = make_user("old_name")

        with pytest.raises(InvalidUsernameError):
            user.change_username("bad name")

        assert user.username == "old_name"
        assert user.pull_events() == []
