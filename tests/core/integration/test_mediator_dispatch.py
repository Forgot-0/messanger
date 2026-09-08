from dataclasses import dataclass

import pytest
from dishka import AsyncContainer

from app.core.commands import BaseCommand
from app.core.exceptions import NotHandlerRegisterError
from app.core.mediators.base import BaseMediator, CommandRegistry, QueryRegistry
from app.core.queries import BaseQuery


@dataclass(frozen=True)
class UnregisteredCommand(BaseCommand):
    value: str = "x"


@dataclass(frozen=True)
class UnregisteredQuery(BaseQuery):
    value: str = "x"


@pytest.mark.integration
@pytest.mark.core
@pytest.mark.asyncio
class TestDishkaMediatorDispatch:

    @pytest.fixture
    async def mediator(self, di_container: AsyncContainer) -> BaseMediator:
        return await di_container.get(BaseMediator)


    async def test_unregistered_command_raises_with_class_name(
        self,
        mediator: BaseMediator,
    ) -> None:
        with pytest.raises(NotHandlerRegisterError) as exc_info:
            await mediator.handle_command(UnregisteredCommand())

        assert exc_info.value.classes == ["UnregisteredCommand"]
        assert exc_info.value.status == 503

    async def test_unregistered_query_raises_with_class_name(
        self,
        mediator: BaseMediator,
    ) -> None:
        with pytest.raises(NotHandlerRegisterError) as exc_info:
            await mediator.handle_query(UnregisteredQuery())

        assert exc_info.value.classes == ["UnregisteredQuery"]


@pytest.mark.unit
@pytest.mark.core
class TestCommandRegistryLookup:

    def test_registries_do_not_share_storage(self) -> None:
        first = CommandRegistry()
        second = CommandRegistry()

        first.register_command(UnregisteredCommand, object)  # type: ignore[arg-type]

        assert second.commands_map == {}

    def test_query_registry_is_independent_of_command_registry(self) -> None:
        commands = CommandRegistry()
        queries = QueryRegistry()

        commands.register_command(UnregisteredCommand, object)  # type: ignore[arg-type]

        assert queries.get_handler_types(UnregisteredQuery()) is None
