from collections.abc import Collection, Iterable
from dataclasses import dataclass

from app.chats.dtos.profiles import ChatProfileDTO
from app.chats.exceptions import UserBlockedError, UserPrivacyRestrictedError
from app.chats.models.chat import Chat, ChatType
from app.chats.repositories.blocks import ChatUserBlockRepository


@dataclass
class ChatPrivacyService:
    block_repository: ChatUserBlockRepository

    async def ensure_can_message(self, chat: Chat, user_id: int) -> None:
        if chat.type != ChatType.DIRECT:
            return

        peer_id = await self.block_repository.blocked_direct_peer(chat.id, user_id)
        if peer_id is not None:
            raise UserBlockedError(chat_id=str(chat.id), user_id=peer_id)

    async def ensure_can_start_direct(self, user_id: int, peer_id: int) -> None:
        if await self.block_repository.is_blocked_between(user_id, peer_id):
            raise UserBlockedError(chat_id=None, user_id=peer_id)

    async def ensure_can_add(self, requester_id: int, target_ids: Collection[int]) -> None:
        restricted = await self.block_repository.blockers_of(
            requester_id, {target_id for target_id in target_ids if target_id != requester_id}
        )
        if restricted:
            raise UserPrivacyRestrictedError(user_ids=sorted(restricted))

    async def hidden_from(self, viewer_id: int, user_ids: Iterable[int]) -> set[int]:
        candidates = {int(user_id) for user_id in user_ids if int(user_id) != viewer_id}

        if not candidates:
            return set()

        return await self.block_repository.blockers_of(viewer_id, candidates)

    async def hide_avatars(
        self, viewer_id: int, profiles: Iterable[ChatProfileDTO | None]
    ) -> None:
        holders = [
            profile
            for profile in profiles
            if profile is not None and (profile.avatar_s3_key or profile.avatar_url)
        ]

        if not holders:
            return

        hidden = await self.hidden_from(viewer_id, (profile.user_id for profile in holders))
        self.strip_avatars(holders, hidden)

    @staticmethod
    def strip_avatars(profiles: Iterable[ChatProfileDTO | None], hidden: set[int]) -> None:
        if not hidden:
            return

        for profile in profiles:
            if profile is not None and profile.user_id in hidden:
                profile.avatar_s3_key = None
                profile.avatar_url = None
