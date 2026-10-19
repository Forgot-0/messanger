from dataclasses import dataclass

from app.core.filters.base import BaseFilter
from app.core.filters.condition import FilterOperator
from app.core.filters.sort import SortDirection


@dataclass
class ProfilePhotoFilter(BaseFilter):
    user_id: int | None = None

    def build_condition(self) -> None:
        self.add_condition("user_id", FilterOperator.EQ, self.user_id)

        self.add_sort("set_main_at", SortDirection.DESC)
        self.add_sort("id", SortDirection.DESC)
