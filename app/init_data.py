import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models.role import Role
from app.auth.models.role_permission import RolesEnum
from app.chats.models.chat_roles import ChatRole
from app.chats.models.permission import ChatRolesEnum
from app.core.di.container import create_container
from app.pre_start import pre_start


async def create_first_data(db: AsyncSession) -> None:
    roles = RolesEnum.get_all_roles()
    for base_role in roles:
        role = await db.execute(select(Role).where(Role.name==base_role.name))

        if role.scalar() is None:
            db.add(base_role)

    chat_roles = ChatRolesEnum.get_all_chat_roles()
    for base_chat_role in chat_roles:
        role = await db.execute(select(ChatRole).where(ChatRole.name == base_chat_role.name))

        if role.scalar() is None:
            db.add(base_chat_role)

    await db.commit()


async def init_data() -> None:
    dishka_container = create_container()
    async with dishka_container() as request_container:
        session = await request_container.get(AsyncSession)
        await pre_start(session)
        await create_first_data(session)


if __name__ == "__main__":
    asyncio.run(init_data())
