import pytest

from app.chats.dtos.avatars import AVATAR_FORMAT_PREFERENCE, CHAT_AVATAR_SIZE, pick_avatar_key


@pytest.mark.unit
@pytest.mark.chats
class TestPickAvatarKey:

    def test_exact_size_wins(self) -> None:
        avatars = {
            "32": {"jpg": "a/32.jpg"},
            str(CHAT_AVATAR_SIZE): {"jpg": "a/64.jpg"},
            "256": {"jpg": "a/256.jpg"},
        }

        assert pick_avatar_key(avatars) == "a/64.jpg"

    def test_numeric_keys_are_accepted(self) -> None:
        assert pick_avatar_key({CHAT_AVATAR_SIZE: {"jpg": "a/64.jpg"}}) == "a/64.jpg"

    def test_format_preference_is_honoured(self) -> None:
        avatars = {
            str(CHAT_AVATAR_SIZE): {
                "avif": "a/64.avif",
                "webp": "a/64.webp",
                "jpg": "a/64.jpg",
            }
        }

        assert AVATAR_FORMAT_PREFERENCE[0] == "jpg"
        assert pick_avatar_key(avatars) == "a/64.jpg"

    def test_next_format_is_used_when_the_preferred_is_missing(self) -> None:
        avatars = {str(CHAT_AVATAR_SIZE): {"avif": "a/64.avif", "webp": "a/64.webp"}}

        assert pick_avatar_key(avatars) == "a/64.webp"

    def test_closest_size_is_used_when_the_exact_one_is_absent(self) -> None:
        avatars = {"32": {"jpg": "a/32.jpg"}, "256": {"jpg": "a/256.jpg"}}

        assert pick_avatar_key(avatars) == "a/32.jpg"

    def test_larger_size_wins_on_an_equal_distance(self) -> None:
        avatars = {"32": {"jpg": "a/32.jpg"}, "96": {"jpg": "a/96.jpg"}}

        assert pick_avatar_key(avatars) == "a/96.jpg"

    def test_size_without_a_usable_format_falls_through_to_the_next(self) -> None:
        avatars = {
            str(CHAT_AVATAR_SIZE): {"heic": "a/64.heic"},
            "128": {"jpg": "a/128.jpg"},
        }

        assert pick_avatar_key(avatars) == "a/128.jpg"

    @pytest.mark.parametrize("avatars", [None, {}, [], "не словарь", 42])
    def test_unusable_input_returns_none(self, avatars: object) -> None:
        assert pick_avatar_key(avatars) is None  # type: ignore[arg-type]

    def test_non_numeric_size_keys_are_ignored(self) -> None:
        assert pick_avatar_key({"large": {"jpg": "a/large.jpg"}}) is None

    def test_non_numeric_key_does_not_break_the_numeric_ones(self) -> None:
        avatars = {"large": {"jpg": "a/large.jpg"}, "64": {"jpg": "a/64.jpg"}}

        assert pick_avatar_key(avatars) == "a/64.jpg"

    def test_empty_string_value_is_not_a_key(self) -> None:
        avatars = {str(CHAT_AVATAR_SIZE): {"jpg": "", "webp": "a/64.webp"}}

        assert pick_avatar_key(avatars) == "a/64.webp"

    def test_non_string_value_is_skipped(self) -> None:
        avatars = {str(CHAT_AVATAR_SIZE): {"jpg": 123, "webp": "a/64.webp"}}

        assert pick_avatar_key(avatars) == "a/64.webp"

    def test_variants_that_are_not_a_mapping_are_skipped(self) -> None:
        avatars = {str(CHAT_AVATAR_SIZE): "a/64.jpg", "128": {"jpg": "a/128.jpg"}}

        assert pick_avatar_key(avatars) == "a/128.jpg"

    def test_whitespace_around_size_keys_is_tolerated(self) -> None:
        assert pick_avatar_key({" 64 ": {"jpg": "a/64.jpg"}}) == "a/64.jpg"

    def test_requested_size_can_be_overridden(self) -> None:
        avatars = {"64": {"jpg": "a/64.jpg"}, "256": {"jpg": "a/256.jpg"}}

        assert pick_avatar_key(avatars, size=256) == "a/256.jpg"

    def test_format_preference_can_be_overridden(self) -> None:
        avatars = {str(CHAT_AVATAR_SIZE): {"jpg": "a/64.jpg", "webp": "a/64.webp"}}

        assert pick_avatar_key(avatars, formats=("webp",)) == "a/64.webp"
