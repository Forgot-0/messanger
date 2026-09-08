from dataclasses import dataclass

import pytest

from app.core.api.filter_mapper import FilterMapper
from app.core.filters.base import BaseFilter
from app.core.filters.condition import FilterCondition, FilterOperator
from app.core.filters.exceptions import PaginationParamsError, ValueMustNotNoneError
from app.core.filters.loading_strategy import (
    LoadingConfig,
    LoadingStrategyType,
    RelationshipLoading,
)
from app.core.filters.pagination import Pagination
from app.core.filters.sort import SortDirection, SortField


@dataclass
class DummyFilter(BaseFilter):
    user_id: int | None = None
    is_read: bool | None = None

    def build_condition(self) -> None:
        self.add_condition("user_id", FilterOperator.EQ, self.user_id)
        self.add_condition("is_read", FilterOperator.EQ, self.is_read)


@pytest.mark.unit
@pytest.mark.core
class TestPagination:

    @pytest.mark.parametrize(
        "page,page_size,offset",
        [(1, 20, 0), (2, 20, 20), (3, 15, 30), (1, 1, 0), (10, 100, 900)],
    )
    def test_offset_is_derived_from_page_and_size(
        self, page: int, page_size: int, offset: int
    ) -> None:
        pagination = Pagination(page=page, page_size=page_size)

        assert pagination.offset == offset
        assert pagination.limit == page_size

    def test_defaults_come_from_the_class_constants(self) -> None:
        pagination = Pagination.default()

        assert pagination.page == Pagination.DEFAULT_PAGE
        assert pagination.page_size == Pagination.DEFAULT_PAGE_SIZE
        assert pagination.offset == 0

    @pytest.mark.parametrize("page", [0, -1, -100])
    def test_non_positive_page_is_rejected(self, page: int) -> None:
        with pytest.raises(PaginationParamsError) as exc_info:
            Pagination(page=page, page_size=20)

        assert exc_info.value.field == "page"

    @pytest.mark.parametrize("page_size", [0, -5])
    def test_non_positive_page_size_is_rejected(self, page_size: int) -> None:
        with pytest.raises(PaginationParamsError) as exc_info:
            Pagination(page=1, page_size=page_size)

        assert exc_info.value.field == "page_size"

    def test_page_size_over_the_cap_is_rejected(self) -> None:
        # Без этой проверки один запрос выгружает всю таблицу в память.
        with pytest.raises(PaginationParamsError) as exc_info:
            Pagination(page=1, page_size=Pagination.MAX_PAGE_SIZE + 1)

        assert exc_info.value.field == "page_size"
        assert exc_info.value.limit == Pagination.MAX_PAGE_SIZE

    def test_the_cap_itself_is_allowed(self) -> None:
        pagination = Pagination(page=1, page_size=Pagination.MAX_PAGE_SIZE)

        assert pagination.limit == Pagination.MAX_PAGE_SIZE


@pytest.mark.unit
@pytest.mark.core
class TestSortStringParsing:

    @pytest.mark.parametrize("raw", [None, "", "   ", ",", " , , "])
    def test_empty_input_yields_no_sort(self, raw: str | None) -> None:
        assert FilterMapper.parse_sort_string(raw) == []

    def test_bare_field_defaults_to_ascending(self) -> None:
        assert FilterMapper.parse_sort_string("username") == [
            SortField(field="username", direction=SortDirection.ASC)
        ]

    def test_direction_suffix_is_honoured(self) -> None:
        assert FilterMapper.parse_sort_string("created_at:desc") == [
            SortField(field="created_at", direction=SortDirection.DESC)
        ]

    def test_several_fields_keep_their_order(self) -> None:
        parsed = FilterMapper.parse_sort_string("created_at:desc,username:asc")

        assert [(f.field, f.direction) for f in parsed] == [
            ("created_at", SortDirection.DESC),
            ("username", SortDirection.ASC),
        ]

    def test_whitespace_around_parts_is_trimmed(self) -> None:
        parsed = FilterMapper.parse_sort_string("  created_at : DESC ,  username  ")

        assert [(f.field, f.direction) for f in parsed] == [
            ("created_at", SortDirection.DESC),
            ("username", SortDirection.ASC),
        ]

    @pytest.mark.parametrize("direction", ["ascending", "up", "1", "desc  extra"])
    def test_unknown_direction_falls_back_to_ascending(self, direction: str) -> None:
        (parsed,) = FilterMapper.parse_sort_string(f"username:{direction}")

        assert parsed.direction == SortDirection.ASC

    def test_extra_colons_stay_in_the_direction_part(self) -> None:
        (parsed,) = FilterMapper.parse_sort_string("a:b:c")

        assert parsed.field == "a"
        assert parsed.direction == SortDirection.ASC


@pytest.mark.unit
@pytest.mark.core
class TestFilterConditions:

    def test_none_value_is_skipped_instead_of_filtering_by_null(self) -> None:
        # Незаданный параметр запроса не должен превращаться в "WHERE x IS NULL".
        empty = DummyFilter()

        assert empty.conditions == ()
        assert empty.has_conditions() is False

    def test_only_provided_values_become_conditions(self) -> None:
        one = DummyFilter(user_id=7)

        assert [(c.field, c.value) for c in one.conditions] == [("user_id", 7)]

    def test_false_is_a_value_and_not_a_skip(self) -> None:
        # Классическая ловушка: is_read=False - валидный фильтр, а не "не задан".
        flt = DummyFilter(is_read=False)

        assert [(c.field, c.value) for c in flt.conditions] == [("is_read", False)]

    @pytest.mark.parametrize(
        "operator",
        [
            FilterOperator.IS_NULL,
            FilterOperator.IS_NOT_NULL,
            FilterOperator.IS_NULL_FROM,
            FilterOperator.IS_NOT_NULL_FROM,
        ],
    )
    def test_null_operators_are_added_without_a_value(
        self, operator: FilterOperator
    ) -> None:
        flt = DummyFilter()
        flt.add_condition("bio", operator, None)

        assert flt.conditions[0].operator is operator
        assert flt.conditions[0].value is None

    def test_non_null_operator_without_a_value_is_a_programming_error(self) -> None:
        with pytest.raises(ValueMustNotNoneError):
            FilterCondition(field="bio", operator=FilterOperator.EQ, value=None)

    def test_conditions_are_exposed_as_an_immutable_tuple(self) -> None:
        flt = DummyFilter(user_id=1)

        assert isinstance(flt.conditions, tuple)

    def test_add_condition_is_chainable(self) -> None:
        flt = DummyFilter()

        result = flt.add_condition("a", FilterOperator.EQ, 1).add_condition(
            "b", FilterOperator.EQ, 2
        )

        assert result is flt
        assert [c.field for c in flt.conditions] == ["a", "b"]

    def test_filters_do_not_share_condition_lists(self) -> None:
        first = DummyFilter(user_id=1)
        second = DummyFilter(user_id=2)

        assert [c.value for c in first.conditions] == [1]
        assert [c.value for c in second.conditions] == [2]


@pytest.mark.unit
@pytest.mark.core
class TestSortAndPaginationOnFilters:

    def test_pagination_defaults_to_page_one(self) -> None:
        assert DummyFilter().pagination.page == Pagination.DEFAULT_PAGE

    def test_pagination_can_be_replaced(self) -> None:
        flt = DummyFilter()

        flt.set_pagination(Pagination(page=3, page_size=5))

        assert flt.pagination.offset == 10

    def test_sort_fields_keep_insertion_order(self) -> None:
        flt = DummyFilter()

        flt.add_sort("created_at", SortDirection.DESC).add_sort("id")

        assert [(f.field, f.direction) for f in flt.sort_fields] == [
            ("created_at", SortDirection.DESC),
            ("id", SortDirection.ASC),
        ]

    def test_is_descending_reflects_the_direction(self) -> None:
        assert SortField("a", SortDirection.DESC).is_descending is True
        assert SortField("a").is_descending is False


@pytest.mark.unit
@pytest.mark.core
class TestLoadingConfig:

    def test_relation_is_registered_with_the_requested_strategy(self) -> None:
        flt = DummyFilter()

        flt.add_relation("contacts", LoadingStrategyType.JOINED)

        rel = flt.loading_config.get_relationship("contacts")
        assert rel is not None
        assert rel.strategy is LoadingStrategyType.JOINED

    def test_registering_the_same_relation_twice_replaces_it(self) -> None:
        flt = DummyFilter()

        flt.add_relation("contacts", LoadingStrategyType.LAZY)
        flt.add_relation("contacts", LoadingStrategyType.SELECTIN)

        assert len(flt.loading_config.relationships) == 1
        assert flt.loading_config.should_load("contacts") is True

    def test_lazy_relation_is_not_eagerly_loaded(self) -> None:
        flt = DummyFilter()

        flt.add_relation("contacts", LoadingStrategyType.LAZY)

        assert flt.loading_config.should_load("contacts") is False

    def test_unknown_relation_is_not_loaded(self) -> None:
        assert LoadingConfig.default().should_load("contacts") is False
        assert LoadingConfig.default().get_relationship("contacts") is None

    def test_nested_relations_are_attached(self) -> None:
        flt = DummyFilter()

        flt.add_relation("members", LoadingStrategyType.SELECTIN, "profile")

        rel = flt.loading_config.get_relationship("members")
        assert rel is not None
        assert rel.has_nested is True
        assert rel.nested is not None
        assert [n.relationship_name for n in rel.nested] == ["profile"]

    def test_relation_without_nested_reports_no_nesting(self) -> None:
        assert RelationshipLoading("contacts").has_nested is False

    def test_eager_all_builds_a_config_from_names(self) -> None:
        config = LoadingConfig.eager_all("a", "b")

        assert [r.relationship_name for r in config.relationships] == ["a", "b"]
        assert config.should_load("a") is True

