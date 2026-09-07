import logging
from dataclasses import dataclass
from datetime import timedelta

from livekit import api as lk_api

from app.chats.config import chat_config
from app.chats.dtos.livekit import LiveKitParticipantsDTO
from app.chats.exceptions import LiveKitServiceError

logger = logging.getLogger(__name__)


@dataclass
class LiveKitService:
    url: str
    api_key: str
    api_secret: str

    def _client(self) -> lk_api.LiveKitAPI:
        return lk_api.LiveKitAPI(
            url=self.url,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

    async def create_room(
        self,
        slug: str,
        max_participants: int | None = None,
        metadata: str = "",
    ) -> None:
        try:
            async with self._client() as client:
                await client.room.create_room(
                    lk_api.CreateRoomRequest(
                        name=slug,
                        max_participants=max_participants or chat_config.ROOM_MAX_PARTICIPANTS,
                        metadata=metadata,
                    )
                )
            logger.info("LiveKit room created", extra={"slug": slug})
        except Exception as exc:
            logger.exception("Failed to create LiveKit room", extra={"slug": slug})
            raise LiveKitServiceError(reason=str(exc)) from exc

    async def delete_room(self, slug: str) -> None:
        try:
            async with self._client() as client:
                await client.room.delete_room(lk_api.DeleteRoomRequest(room=slug))
            logger.info("LiveKit room deleted", extra={"slug": slug})
        except Exception as exc:
            logger.exception("Failed to delete LiveKit room", extra={"slug": slug})
            raise LiveKitServiceError(reason=str(exc)) from exc

    def generate_join_token(
        self,
        slug: str,
        user_id: str,
        username: str,
        can_publish: bool = True,
        can_subscribe: bool = True,
        can_publish_data: bool = True,
        room_admin: bool = False,
    ) -> str:
        token = lk_api.AccessToken(api_key=self.api_key, api_secret=self.api_secret)
        token.with_identity(user_id)
        token.with_name(username)
        token.with_ttl(timedelta(seconds=chat_config.ROOM_TOKEN_TTL))
        token.with_grants(
            lk_api.VideoGrants(
                room_join=True,
                room=slug,
                can_publish=can_publish,
                can_subscribe=can_subscribe,
                can_publish_data=can_publish_data,
                room_admin=room_admin,
            )
        )
        return token.to_jwt()

    async def remove_participant(self, slug: str, identity: str) -> None:
        try:
            async with self._client() as client:
                await client.room.remove_participant(
                    lk_api.RoomParticipantIdentity(room=slug, identity=identity)
                )
            logger.info(
                "LiveKit participant removed",
                extra={"slug": slug, "identity": identity},
            )
        except Exception as exc:
            logger.warning(
                "Could not remove LiveKit participant",
                extra={"slug": slug, "identity": identity, "error": str(exc)},
            )

    async def mute_participant(
        self,
        slug: str,
        identity: str,
        muted: bool = True,
    ) -> None:
        try:
            async with self._client() as client:
                participant = await client.room.get_participant(
                    lk_api.RoomParticipantIdentity(room=slug, identity=identity)
                )
                for track in participant.tracks:
                    if track.type in (0, 1):
                        await client.room.mute_published_track(
                            lk_api.MuteRoomTrackRequest(
                                room=slug,
                                identity=identity,
                                track_sid=track.sid,
                                muted=muted,
                            )
                        )
            action = "muted" if muted else "unmuted"
            logger.info(
                "LiveKit participant %s", action,
                extra={"slug": slug, "identity": identity},
            )
        except Exception as exc:
            logger.warning(
                "Could not mute LiveKit participant",
                extra={"slug": slug, "identity": identity, "error": str(exc)},
            )
            raise LiveKitServiceError(reason=str(exc)) from exc

    async def list_participants(self, slug: str) -> list[LiveKitParticipantsDTO]:
        try:
            async with self._client() as client:
                resp = await client.room.list_participants(
                    lk_api.ListParticipantsRequest(room=slug)
                )
            return [
                LiveKitParticipantsDTO(
                    identity=p.identity,
                    name=p.name,
                    state=p.state,
                    joined_at=p.joined_at,
                )
                for p in resp.participants
            ]
        except Exception as exc:
            logger.warning(
                "Could not list LiveKit participants",
                extra={"slug": slug, "error": str(exc)},
            )
            return []
