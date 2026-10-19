from uuid import uuid7

import pytest

from app.profiles.models.photo import ProfilePhoto
from app.profiles.models.profile import Profile, ProfileUpdated


def make_profile() -> Profile:
    profile = Profile.create(
        user_id=11, username="owner", display_name="Owner", specialization=None, bio=None
    )
    profile.pull_events()
    return profile


def make_photo(user_id: int = 11) -> ProfilePhoto:
    photo_id = uuid7()
    return ProfilePhoto.create(
        photo_id=photo_id, user_id=user_id, avatars={64: {"jpg": f"{user_id}/{photo_id}/64.jpg"}}
    )


@pytest.mark.unit
@pytest.mark.profiles
class TestProfilePhotoModel:

    def test_set_photo_points_the_profile_at_it(self) -> None:
        profile = make_profile()
        photo = make_photo()

        profile.set_photo(photo)

        assert profile.photo_id == photo.id
        assert profile.avatars == photo.avatars
        event = profile.pull_events()[0]
        assert isinstance(event, ProfileUpdated)
        assert event.avatars == photo.avatars

    def test_clearing_the_photo_empties_the_avatar(self) -> None:
        profile = make_profile()
        profile.set_photo(make_photo())
        profile.pull_events()

        profile.set_photo(None)

        assert profile.photo_id is None and profile.avatars == {}
        assert profile.pull_events()[0].avatars == {}  # type: ignore[attr-defined]

    def test_make_main_moves_the_photo_to_the_front(self) -> None:
        photo = make_photo()
        before = photo.set_main_at

        photo.make_main()

        assert photo.set_main_at >= before


@pytest.mark.unit
@pytest.mark.profiles
class TestProfileUsername:

    def test_new_username_is_announced(self) -> None:
        profile = make_profile()

        profile.change_username("renamed")

        assert profile.username == "renamed"
        event = profile.pull_events()[0]
        assert isinstance(event, ProfileUpdated)
        assert event.username == "renamed"
        assert event.display_name == "Owner"

    def test_same_username_is_silent(self) -> None:
        profile = make_profile()

        profile.change_username("owner")

        assert profile.pull_events() == []
