from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, status

from app.chats.commands.attachments.request_upload import (
    RequestAttachmentUploadCommand,
    UploadRequest,
)
from app.chats.commands.attachments.success import SuccessUploadAttachmentsCommand
from app.chats.dtos.attachments import AttachmentDownloadUrlDTO, UploadSlotDTO
from app.chats.queries.attachments.get_url import GetAttachmentDownloadUrlQuery
from app.chats.schemas.rest import ConfirmAttachmentUploadRequest, RequestAttachmentUploadRequest
from app.core.mediators.base import BaseMediator
from app.core.services.auth.depends import CurrentUserJWTData

router = APIRouter(route_class=DishkaRoute)


@router.post(
    "/attachments/upload-requests/",
    status_code=status.HTTP_201_CREATED
)
async def request_attachment_upload(
    chat_id: UUID,
    payload: RequestAttachmentUploadRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> list[UploadSlotDTO]:
    slotts = await mediator.handle_command(
        RequestAttachmentUploadCommand(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            uploads=[
                UploadRequest(
                    filename=item.filename,
                    mime_type=item.mime_type,
                    file_size=item.file_size,
                    attachment_type=item.attachment_type
                )
                for item in payload.uploads
            ],
        )
    )

    return slotts

@router.post(
    "/attachments/upload-requests/confirm/",
    status_code=status.HTTP_202_ACCEPTED
)
async def confirm_attachment_upload(
    chat_id: UUID,
    payload: ConfirmAttachmentUploadRequest,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> None:
    await mediator.handle_command(
        SuccessUploadAttachmentsCommand(
            chat_id=chat_id,
            upload_tokens=[str(token) for token in payload.upload_tokens],
            user_jwt_data=user_jwt_data,
        )
    )

@router.get(
    "/messages/{message_id}/attachments/{attachment_id}/download-url/",
    status_code=status.HTTP_200_OK
)
async def get_attachment_download_url(
    chat_id: UUID,
    message_id: UUID,
    attachment_id: UUID,
    user_jwt_data: CurrentUserJWTData,
    mediator: FromDishka[BaseMediator],
) -> AttachmentDownloadUrlDTO:
    return await mediator.handle_query(
        GetAttachmentDownloadUrlQuery(
            user_jwt_data=user_jwt_data,
            chat_id=chat_id,
            message_id=message_id,
            attachment_id=attachment_id,
        )
    )
