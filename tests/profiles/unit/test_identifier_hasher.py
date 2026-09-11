import hashlib
import hmac

import pytest

from app.profiles.exceptions import IdentifierPepperNotConfiguredError
from app.profiles.models.contacts import IdentifierKind
from app.profiles.services.identifier_hasher import IdentifierHasher

PEPPER = "unit-test-pepper"


@pytest.fixture
def hasher() -> IdentifierHasher:
    return IdentifierHasher(pepper=PEPPER)


@pytest.mark.unit
class TestNormalizeEmail:

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("user@example.com", "user@example.com"),
            ("  User@Example.COM  ", "user@example.com"),
            ("USER+tag@mail.example.org", "user+tag@mail.example.org"),
        ],
    )
    def test_valid_email_is_trimmed_and_lowercased(
        self, hasher: IdentifierHasher, raw: str, expected: str
    ) -> None:
        assert hasher.normalize_email(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["", "   ", None, "not-an-email", "@example.com", "user@", "user@localhost", "a b@c.com"],
    )
    def test_garbage_is_rejected(self, hasher: IdentifierHasher, raw: str | None) -> None:
        assert hasher.normalize_email(raw) is None

    def test_too_long_email_is_rejected(self, hasher: IdentifierHasher) -> None:
        assert hasher.normalize_email(f"{'a' * 60}@{'b' * 300}.com") is None


@pytest.mark.unit
class TestNormalizePhone:
    """Телефон как идентификатор ещё не заводится, но схема обязана принять
    его позже без миграции контактов."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("+7 (999) 123-45-67", "+79991234567"),
            ("79991234567", "+79991234567"),
            ("+1 415 555 0132", "+14155550132"),
        ],
    )
    def test_digits_only_with_leading_plus(
        self, hasher: IdentifierHasher, raw: str, expected: str
    ) -> None:
        assert hasher.normalize_phone(raw) == expected

    @pytest.mark.parametrize("raw", ["", None, "123", "0123456789", "9" * 20, "abc"])
    def test_garbage_is_rejected(self, hasher: IdentifierHasher, raw: str | None) -> None:
        assert hasher.normalize_phone(raw) is None


@pytest.mark.unit
class TestHashing:

    def test_hash_is_hmac_sha256_over_normalized_value(self, hasher: IdentifierHasher) -> None:
        expected = hmac.new(
            PEPPER.encode(), b"user@example.com", hashlib.sha256
        ).digest()

        assert hasher.hash(IdentifierKind.EMAIL, "  User@Example.com ") == expected
        assert len(expected) == 32

    def test_same_email_written_differently_gives_one_hash(
        self, hasher: IdentifierHasher
    ) -> None:
        assert hasher.hash(IdentifierKind.EMAIL, "USER@EXAMPLE.COM") == hasher.hash(
            IdentifierKind.EMAIL, "user@example.com"
        )

    def test_different_emails_give_different_hashes(self, hasher: IdentifierHasher) -> None:
        assert hasher.hash(IdentifierKind.EMAIL, "a@example.com") != hasher.hash(
            IdentifierKind.EMAIL, "b@example.com"
        )

    def test_pepper_changes_the_hash(self, hasher: IdentifierHasher) -> None:
        other = IdentifierHasher(pepper="another-pepper")

        assert hasher.hash(IdentifierKind.EMAIL, "user@example.com") != other.hash(
            IdentifierKind.EMAIL, "user@example.com"
        )

    def test_unparsable_identifier_has_no_hash(self, hasher: IdentifierHasher) -> None:
        assert hasher.hash(IdentifierKind.EMAIL, "not-an-email") is None
        assert hasher.hash(IdentifierKind.PHONE, "123") is None

    def test_phone_and_email_share_the_hash_space_without_collisions(
        self, hasher: IdentifierHasher
    ) -> None:
        email_hash = hasher.hash(IdentifierKind.EMAIL, "user@example.com")
        phone_hash = hasher.hash(IdentifierKind.PHONE, "+79991234567")

        assert email_hash != phone_hash

    def test_empty_pepper_is_a_configuration_error(self) -> None:
        with pytest.raises(IdentifierPepperNotConfiguredError):
            IdentifierHasher(pepper="   ").hash(IdentifierKind.EMAIL, "user@example.com")
