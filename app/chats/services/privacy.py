from collections.abc import Collection, Iterable
from dataclasses import dataclass

from app.chats.dtos.profiles import ChatProfileDTO
from app.chats.exceptions import (
    CallsPrivacyRestrictedError,
    MessagesPrivacyRestrictedError,
    UserBlockedError,
    UserPrivacyRestrictedError,
)
from app.chats.models.chat import Chat, ChatType
from app.chats.repositories.blocks import ChatUserBlockRepository
from app.chats.repositories.privacy import ChatPrivacyProjectionRepository, DirectPeerState
from app.privacy.utils import DEFAULT_VISIBILITY, PrivacyRule, PrivacyVisibility, is_allowed


@dataclass
class ChatPrivacyService:
    block_repository: ChatUserBlockRepository
    privacy_repository: ChatPrivacyProjectionRepository

    async def ensure_can_message(self, chat: Chat, user_id: int) -> None:
        if chat.type != ChatType.DIRECT:
            return

        state = await self.privacy_repository.direct_peer_state(
            chat.id, user_id, PrivacyRule.MESSAGES
        )
        if state is None:
            return

        if state.blocked:
            raise UserBlockedError(chat_id=str(chat.id), user_id=state.peer_id)

        if not await self._peer_allows(state, user_id):
            raise MessagesPrivacyRestrictedError(chat_id=str(chat.id), user_id=state.peer_id)

    async def ensure_can_call(self, chat: Chat, user_id: int) -> None:
        if chat.type != ChatType.DIRECT:
            return

        state = await self.privacy_repository.direct_peer_state(
            chat.id, user_id, PrivacyRule.CALLS
        )
        if state is None:
            return

        if state.blocked:
            raise UserBlockedError(chat_id=str(chat.id), user_id=state.peer_id)

        if not await self._peer_allows(state, user_id):
            raise CallsPrivacyRestrictedError(chat_id=str(chat.id), user_id=state.peer_id)

    async def ensure_can_start_direct(self, user_id: int, peer_id: int) -> None:
        if await self.block_repository.is_blocked_between(user_id, peer_id):
            raise UserBlockedError(chat_id=None, user_id=peer_id)

        allowed = await self.allowed_by(PrivacyRule.MESSAGES, user_id, [peer_id])
        if peer_id not in allowed:
            raise MessagesPrivacyRestrictedError(chat_id=None, user_id=peer_id)

    async def ensure_can_add(self, requester_id: int, target_ids: Collection[int]) -> None:
        targets = {int(target_id) for target_id in target_ids if int(target_id) != requester_id}
        if not targets:
            return

        restricted = await self.block_repository.blockers_of(requester_id, targets)

        rest = targets - restricted
        if rest:
            allowed = await self.allowed_by(PrivacyRule.GROUP_INVITES, requester_id, rest)
            restricted |= rest - allowed

        if restricted:
            raise UserPrivacyRestrictedError(user_ids=sorted(restricted))

    async def hidden_photos(self, viewer_id: int, user_ids: Iterable[int]) -> set[int]:
        return await self._hidden_by_rule(PrivacyRule.PHOTO, viewer_id, user_ids)

    async def hidden_presence(self, viewer_id: int, user_ids: Iterable[int]) -> set[int]:
        return await self._hidden_by_rule(PrivacyRule.LAST_SEEN, viewer_id, user_ids)

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

        hidden = await self.hidden_photos(viewer_id, (profile.user_id for profile in holders))
        self.strip_avatars(holders, hidden)

    async def allowed_by(
        self, rule: PrivacyRule, viewer_id: int, owner_ids: Iterable[int]
    ) -> set[int]:
        owners = {int(owner_id) for owner_id in owner_ids}
        if not owners:
            return set()

        allowed: set[int] = set()
        if viewer_id in owners:
            allowed.add(viewer_id)
            owners.discard(viewer_id)

        if not owners:
            return allowed

        visibility = await self.privacy_repository.visibility_map(rule, owners)
        exceptions = await self.privacy_repository.exceptions_for(rule, viewer_id, owners)

        need_contacts = {
            owner_id
            for owner_id in owners
            if owner_id not in exceptions
            and visibility.get(owner_id, DEFAULT_VISIBILITY) is PrivacyVisibility.CONTACTS
        }
        contacts: set[int] = set()
        if need_contacts:
            contacts = await self.privacy_repository.contacts_of(viewer_id, need_contacts)

        for owner_id in owners:
            if is_allowed(
                visibility.get(owner_id, DEFAULT_VISIBILITY),
                is_contact=owner_id in contacts,
                exception=exceptions.get(owner_id),
            ):
                allowed.add(owner_id)

        return allowed

    @staticmethod
    def strip_avatars(profiles: Iterable[ChatProfileDTO | None], hidden: set[int]) -> None:
        if not hidden:
            return

        for profile in profiles:
            if profile is not None and profile.user_id in hidden:
                profile.avatar_s3_key = None
                profile.avatar_url = None

    async def _hidden_by_rule(
        self, rule: PrivacyRule, viewer_id: int, user_ids: Iterable[int]
    ) -> set[int]:
        candidates = {int(user_id) for user_id in user_ids if int(user_id) != viewer_id}
        if not candidates:
            return set()

        hidden = await self.block_repository.blockers_of(viewer_id, candidates)

        rest = candidates - hidden
        if rest:
            hidden |= rest - await self.allowed_by(rule, viewer_id, rest)

        return hidden

    async def _peer_allows(self, state: DirectPeerState, viewer_id: int) -> bool:
        is_contact = False
        if state.exception is None and state.visibility is PrivacyVisibility.CONTACTS:
            is_contact = bool(
                await self.privacy_repository.contacts_of(viewer_id, [state.peer_id])
            )

        return is_allowed(
            state.visibility,
            is_contact=is_contact,
            exception=state.exception,
        )
