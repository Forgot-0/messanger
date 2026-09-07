
from datetime import date
from typing import Any


class ProfileCommandFactory:
    @staticmethod
    def create_command(
        user_id: int,
        username: str,
        specialization: str | None=None,
        display_name: str | None=None,
        bio: str | None = None,
        skills: set[str] | None=None,
        date_birthday: date | None=None,
    ) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "username": username,
            "specialization": specialization,
            "display_name": display_name,
            "bio": bio,
            "skills": skills,
            "date_birthday": date_birthday,
        }

    @staticmethod
    def update_command(
        specialization: str | None=None,
        display_name: str | None=None,
        bio: str | None = None,
        skills: set[str] | None=None,
        date_birthday: date | None=None,
    ) -> dict[str, Any]:
        return {
            "specialization": specialization,
            "display_name": display_name,
            "bio": bio,
            "skills": skills,
            "date_birthday": date_birthday,
        }

