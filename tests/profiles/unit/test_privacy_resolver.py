import pytest

from app.privacy.utils import PrivacyRule, PrivacyVisibility, is_allowed


@pytest.mark.unit
class TestIsAllowed:

    def test_self_is_always_allowed(self) -> None:
        assert is_allowed(PrivacyVisibility.NOBODY, is_self=True) is True
        assert is_allowed(PrivacyVisibility.NOBODY, is_self=True, exception=False) is True

    def test_everybody_allows_a_stranger(self) -> None:
        assert is_allowed(PrivacyVisibility.EVERYBODY) is True

    def test_contacts_needs_a_contact(self) -> None:
        assert is_allowed(PrivacyVisibility.CONTACTS, is_contact=True) is True
        assert is_allowed(PrivacyVisibility.CONTACTS, is_contact=False) is False

    def test_nobody_allows_nobody(self) -> None:
        assert is_allowed(PrivacyVisibility.NOBODY, is_contact=True) is False

    def test_exception_beats_visibility_both_ways(self) -> None:
        assert is_allowed(PrivacyVisibility.NOBODY, exception=True) is True
        assert is_allowed(PrivacyVisibility.EVERYBODY, exception=False) is False
        assert is_allowed(PrivacyVisibility.CONTACTS, is_contact=True, exception=False) is False

    def test_rule_values_are_column_names(self) -> None:
        """Значение правила — имя колонки в profile_privacy и суффикс в проекции."""
        assert {rule.value for rule in PrivacyRule} == {
            "last_seen", "photo", "messages", "group_invites", "calls",
        }
