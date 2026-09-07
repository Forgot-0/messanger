from dataclasses import dataclass

from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData
from app.core.services.storage.service import StorageService
from app.profiles.config import profile_config
from app.profiles.dtos.profiles import AvatarPresign
from app.profiles.repositories.profiles import ProfileRepository


@dataclass(frozen=True)
class GetAvatrProfileUrlQuery(BaseQuery):
    file_name: str
    user_id: int
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class GetAvatrProfileUrlQueryHandler(BaseQueryHandler[GetAvatrProfileUrlQuery, AvatarPresign]):
    storage_service: StorageService
    profile_repository: ProfileRepository

    async def handle(self, query: GetAvatrProfileUrlQuery) -> AvatarPresign:
        return await self.profile_repository.cache(
            AvatarPresign, self._handle, ttl=90,
            query=query
        )

    async def _handle(self, query: GetAvatrProfileUrlQuery) -> AvatarPresign:
        file_key = f"{query.user_id}/{self.storage_service.clean_filename(query.file_name)}"

        result = await self.storage_service.upload_put_url(
            bucket_name=profile_config.PENDING_AVATAR_BUCKET, file_key=file_key,
            expires=90
        )
        return AvatarPresign(
            url=result,
            file_key=file_key
        )
