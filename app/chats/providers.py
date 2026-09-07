from dishka import Provider, Scope, decorate, provide, provide_all

from app.chats.commands.attachments.proccess import ProccessAttachmentsCommand, ProccessAttachmentsCommandHandler
from app.chats.commands.attachments.request_upload import (
    RequestAttachmentUploadCommand,
    RequestAttachmentUploadCommandHandler,
)
from app.chats.commands.attachments.success import (
    SuccessUploadAttachmentsCommand,
    SuccessUploadAttachmentsCommandHandler,
)
from app.chats.commands.calls.join import JoinCallCommand, JoinCallCommandHandler
from app.chats.commands.calls.mute import MuteParticipantCommand, MuteParticipantCommandHandler
from app.chats.commands.chats.add_member import AddMemberCommand, AddMemberCommandHandler
from app.chats.commands.chats.ban_member import BanMemberCommand, BanMemberCommandHandler
from app.chats.commands.chats.change_role import ChangeMemberRoleCommand, ChangeMemberRoleCommandHandler
from app.chats.commands.chats.create import CreateChatCommand, CreateChatCommandHandler
from app.chats.commands.chats.delete import DeleteChatCommand, DeleteChatCommandHandler
from app.chats.commands.chats.join import JoinChatCommand, JoinChatCommandHandler
from app.chats.commands.chats.kick import KickMemberCommand, KickMemberCommandHandler
from app.chats.commands.chats.leave import LeaveChatCommand, LeaveChatCommandHandler
from app.chats.commands.chats.update import UpdateChatCommand, UpdateChatCommandHandler
from app.chats.commands.messages.delete import DeleteMessageCommand, DeleteMessageCommandHandler
from app.chats.commands.messages.forward import ForwardMessageCommand, ForwardMessageCommandHandler
from app.chats.commands.messages.mark_read import MarkAsReadCommand, MarkAsReadCommandHandler
from app.chats.commands.messages.modify import EditMessageCommand, EditMessageCommandHandler
from app.chats.commands.messages.send import SendMessageCommand, SendMessageCommandHandler
from app.chats.commands.profiles.upsert import UpsertProfileProjectionCommand, UpsertProfileProjectionCommandHandler
from app.chats.commands.reactions.remove import RemoveReactionCommand, RemoveReactionCommandHandler
from app.chats.commands.reactions.set import SetReactionCommand, SetReactionCommandHandler
from app.chats.commands.reactions.set_many import SetReactionsCommand, SetReactionsCommandHandler
from app.chats.commands.websockets.ping import PingCommand, PingCommandHandler
from app.chats.commands.websockets.pong import PongCommand, PongCommandHandler
from app.chats.commands.websockets.resume import ResumeCommand, ResumeCommandHandler
from app.chats.commands.websockets.subscribe import SubscribeCommand, SubscribeCommandHandler
from app.chats.commands.websockets.unsubscribe import UnsubscribeCommand, UnsubscribeCommandHandler
from app.chats.config import chat_config
from app.chats.queries.attachments.get_url import GetAttachmentDownloadUrlQuery, GetAttachmentDownloadUrlQueryHandler
from app.chats.queries.chats.get_detail import GetChatDetailQuery, GetChatDetailQueryHandler
from app.chats.queries.chats.get_list import GetListChatUserQuery, GetListChatUserQueryHandler
from app.chats.queries.chats.get_members import GetChatMembersQuery, GetChatMembersQueryHandler
from app.chats.queries.messages.get_context import GetMessageContextQuery, GetMessageContextQueryHandler
from app.chats.queries.messages.get_detail import GetMessageDetailQuery, GetMessageDetailQueryHandler
from app.chats.queries.messages.get_list import GetMessagesQuery, GetMessagesQueryHandler
from app.chats.queries.reactions.get_list import (
    GetMessageReactionsQuery,
    GetMessageReactionsQueryHandler,
)
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.repositories.reaction import MessageReactionRepository
from app.chats.repositories.reads import ReadReceiptRepository
from app.chats.repositories.user_profile import ChatUserProfileRepository
from app.chats.services.access import ChatAccessService
from app.chats.services.attachment_media import AttachmentMediaValidator
from app.chats.services.delivery_router import ChatDeliveryRouter
from app.chats.services.livekit_service import LiveKitService
from app.chats.services.messages import MessageService
from app.chats.services.reaction_attach import ReactionAttachService
from app.chats.services.reaction_coalescer import ReactionCoalesceQueue
from app.chats.services.reaction_policy import ReactionPolicy
from app.core.events.event import EventRegistry
from app.core.mediators.base import CommandRegistry, QueryRegistry
from app.core.services.storage.aminio.policy import Policy


class ChatModuleProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def livekit_service(self) -> LiveKitService:
        return LiveKitService(
            url=chat_config.LIVEKIT_URL,
            api_key=chat_config.LIVEKIT_API_KEY,
            api_secret=chat_config.LIVEKIT_API_SECRET,
        )

    delivery_router = provide(ChatDeliveryRouter, scope=Scope.REQUEST)
    reaction_attach_service = provide(ReactionAttachService, scope=Scope.REQUEST)
    reaction_coalesce_queue = provide(ReactionCoalesceQueue, scope=Scope.APP)

    commands = provide_all(
        RequestAttachmentUploadCommandHandler,
        SuccessUploadAttachmentsCommandHandler,
        ProccessAttachmentsCommandHandler,
        JoinCallCommandHandler,
        MuteParticipantCommandHandler,
        AddMemberCommandHandler,
        BanMemberCommandHandler,
        ChangeMemberRoleCommandHandler,
        CreateChatCommandHandler,
        DeleteChatCommandHandler,
        JoinChatCommandHandler,
        KickMemberCommandHandler,
        LeaveChatCommandHandler,
        UpdateChatCommandHandler,
        DeleteMessageCommandHandler,
        ForwardMessageCommandHandler,
        MarkAsReadCommandHandler,
        EditMessageCommandHandler,
        SendMessageCommandHandler,
        PingCommandHandler,
        PongCommandHandler,
        ResumeCommandHandler,
        SubscribeCommandHandler,
        UnsubscribeCommandHandler,
        UpsertProfileProjectionCommandHandler,
        SetReactionCommandHandler,
        RemoveReactionCommandHandler,
        SetReactionsCommandHandler,
        scope=Scope.REQUEST,
    )

    queries = provide_all(
        GetAttachmentDownloadUrlQueryHandler,
        GetChatDetailQueryHandler,
        GetListChatUserQueryHandler,
        GetChatMembersQueryHandler,
        GetMessageContextQueryHandler,
        GetMessageDetailQueryHandler,
        GetMessagesQueryHandler,
        GetMessageReactionsQueryHandler,
        scope=Scope.REQUEST,
    )

    repositories = provide_all(
        ChatRepository,
        MessageRepository,
        MessageReactionRepository,
        AttachmentRepository,
        ReadReceiptRepository,
        ChatUserProfileRepository,
        scope=Scope.REQUEST,
    )

    service = provide_all(
        MessageService,
        ChatAccessService,
        AttachmentMediaValidator,
        ReactionPolicy,
        scope=Scope.APP
    )

    @decorate
    def register_auth_command_handlers(self, command_registry: CommandRegistry) -> CommandRegistry:
        command_registry.register_command(RequestAttachmentUploadCommand, RequestAttachmentUploadCommandHandler)
        command_registry.register_command(SuccessUploadAttachmentsCommand, SuccessUploadAttachmentsCommandHandler)
        command_registry.register_command(ProccessAttachmentsCommand, ProccessAttachmentsCommandHandler)
        command_registry.register_command(JoinCallCommand, JoinCallCommandHandler)
        command_registry.register_command(MuteParticipantCommand, MuteParticipantCommandHandler)
        command_registry.register_command(AddMemberCommand, AddMemberCommandHandler)
        command_registry.register_command(BanMemberCommand, BanMemberCommandHandler)
        command_registry.register_command(ChangeMemberRoleCommand, ChangeMemberRoleCommandHandler)
        command_registry.register_command(CreateChatCommand, CreateChatCommandHandler)
        command_registry.register_command(DeleteChatCommand, DeleteChatCommandHandler)
        command_registry.register_command(JoinChatCommand, JoinChatCommandHandler)
        command_registry.register_command(KickMemberCommand, KickMemberCommandHandler)
        command_registry.register_command(LeaveChatCommand, LeaveChatCommandHandler)
        command_registry.register_command(UpdateChatCommand, UpdateChatCommandHandler)
        command_registry.register_command(DeleteMessageCommand, DeleteMessageCommandHandler)
        command_registry.register_command(ForwardMessageCommand, ForwardMessageCommandHandler)
        command_registry.register_command(MarkAsReadCommand, MarkAsReadCommandHandler)
        command_registry.register_command(EditMessageCommand, EditMessageCommandHandler)
        command_registry.register_command(SendMessageCommand, SendMessageCommandHandler)

        command_registry.register_command(PingCommand, PingCommandHandler)
        command_registry.register_command(PongCommand, PongCommandHandler)
        command_registry.register_command(ResumeCommand, ResumeCommandHandler)
        command_registry.register_command(SubscribeCommand, SubscribeCommandHandler)
        command_registry.register_command(UnsubscribeCommand, UnsubscribeCommandHandler)
        command_registry.register_command(UpsertProfileProjectionCommand, UpsertProfileProjectionCommandHandler)
        command_registry.register_command(SetReactionCommand, SetReactionCommandHandler)
        command_registry.register_command(RemoveReactionCommand, RemoveReactionCommandHandler)
        command_registry.register_command(SetReactionsCommand, SetReactionsCommandHandler)
        return command_registry

    @decorate
    def register_auth_query_handlers(self, query_registry: QueryRegistry) -> QueryRegistry:
        query_registry.register_query(GetAttachmentDownloadUrlQuery, GetAttachmentDownloadUrlQueryHandler)
        query_registry.register_query(GetChatDetailQuery, GetChatDetailQueryHandler)
        query_registry.register_query(GetListChatUserQuery, GetListChatUserQueryHandler)
        query_registry.register_query(GetChatMembersQuery, GetChatMembersQueryHandler)
        query_registry.register_query(GetMessageContextQuery, GetMessageContextQueryHandler)
        query_registry.register_query(GetMessageDetailQuery, GetMessageDetailQueryHandler)
        query_registry.register_query(GetMessagesQuery, GetMessagesQueryHandler)
        query_registry.register_query(GetMessageReactionsQuery, GetMessageReactionsQueryHandler)
        return query_registry

    @decorate
    def register_auth_event_handlers(self, event_registry: EventRegistry) -> EventRegistry:
        return event_registry

    @decorate
    def bucket_policy(self, policy: dict[str, Policy]) -> dict[str, Policy]:
        policy[chat_config.ATTACHMENT_BUCKET] = Policy.NONE
        policy[chat_config.ATTACHMENT_BUCKET_PENDING] = Policy.NONE
        return policy
