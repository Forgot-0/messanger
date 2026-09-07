from dataclasses import dataclass

from app.core.filters.base import BaseFilter
from app.core.filters.condition import FilterOperator


@dataclass
class ProfileFilter(BaseFilter):
    username: str | None = None
    display_name: str | None = None
    skills: list[str] | None = None

    def build_condition(self) -> None:
        self.add_condition("username", FilterOperator.CONTAINS, self.username)
        self.add_condition("display_name", FilterOperator.CONTAINS, self.display_name)

        if self.skills:
            self.skills = [skill.lower() for skill in self.skills]

        self.add_condition("skills", FilterOperator.ALL, self.skills)

        self.add_relation("contacts")
