from dishka import Provider, Scope, decorate, provide

from app.core.events.event import EventRegistry
from app.core.mediators.base import CommandRegistry, QueryRegistry
from app.core.services.storage.aminio.policy import Policy
from app.profiles.commands.contacts.add import AddContactCommand, AddContactCommandHandler
from app.profiles.commands.contacts.block import BlockUserCommand, BlockUserCommandHandler
from app.profiles.commands.contacts.import_batch import ImportContactsCommand, ImportContactsCommandHandler
from app.profiles.commands.contacts.register_identifier import (
    RegisterUserIdentifierCommand,
    RegisterUserIdentifierCommandHandler,
)
from app.profiles.commands.contacts.remove import RemoveContactCommand, RemoveContactCommandHandler
from app.profiles.commands.contacts.unblock import UnblockUserCommand, UnblockUserCommandHandler
from app.profiles.commands.contacts.update import UpdateContactCommand, UpdateContactCommandHandler
from app.profiles.commands.profiles.add_link import AddLinkToProfileCommand, AddLinkToProfileCommandHandler
from app.profiles.commands.profiles.create import CreateProfileCommand, CreateProfileCommandHanler
from app.profiles.commands.profiles.get_or_create import GetOrCreateProfileCommand, GetOrCreateProfileCommandHanler
from app.profiles.commands.profiles.proccess_avatar import ProccessAvatarCommand, ProccessAvatarCommandHandler
from app.profiles.commands.profiles.remove_link import (
    RemoveLinkFromProfileCommand,
    RemoveLinkFromProfileCommandHandler,
)
from app.profiles.commands.profiles.update import UpdateProfileCommand, UpdateProfileCommandHandler
from app.profiles.commands.profiles.update_avatar import UpdateProfileAvatarCommand, UpdateProfileAvatarCommandHandler
from app.profiles.config import profile_config
from app.profiles.queries.contacts.get_blocked import GetBlockedUsersQuery, GetBlockedUsersQueryHandler
from app.profiles.queries.contacts.get_list import GetContactsQuery, GetContactsQueryHandler
from app.profiles.queries.contacts.search import SearchContactsQuery, SearchContactsQueryHandler
from app.profiles.queries.profiles.get_by_id import GetProfileByIdQuery, GetProfileByIdQueryHandler
from app.profiles.queries.profiles.get_list import GetProfilesQuery, GetProfilesQueryHandler
from app.profiles.queries.profiles.get_url import GetAvatrProfileUrlQuery, GetAvatrProfileUrlQueryHandler
from app.profiles.repositories.contacts import (
    BlockedUserRepository,
    ContactIdentifierRepository,
    ContactRepository,
)
from app.profiles.repositories.profiles import ProfileRepository
from app.profiles.services.identifier_hasher import IdentifierHasher


class ProfileModuleProvider(Provider):
    scope = Scope.REQUEST

    profile_repository = provide(ProfileRepository)
    contact_repository = provide(ContactRepository)
    contact_identifier_repository = provide(ContactIdentifierRepository)
    blocked_user_repository = provide(BlockedUserRepository)

    @provide(scope=Scope.APP)
    def identifier_hasher(self) -> IdentifierHasher:
        return IdentifierHasher(pepper=profile_config.CONTACT_IDENTIFIER_PEPPER)


    create_profile_handler = provide(CreateProfileCommandHanler)
    update_profile_handler = provide(UpdateProfileCommandHandler)
    update_avatar_profile_handler = provide(UpdateProfileAvatarCommandHandler)
    process_avatar_handler = provide(ProccessAvatarCommandHandler)
    add_link_profile_handler = provide(AddLinkToProfileCommandHandler)
    remove_link_profile_handler = provide(RemoveLinkFromProfileCommandHandler)
    get_or_create_provider = provide(GetOrCreateProfileCommandHanler)

    add_contact_handler = provide(AddContactCommandHandler)
    remove_contact_handler = provide(RemoveContactCommandHandler)
    update_contact_handler = provide(UpdateContactCommandHandler)
    import_contacts_handler = provide(ImportContactsCommandHandler)
    register_identifier_handler = provide(RegisterUserIdentifierCommandHandler)
    block_user_handler = provide(BlockUserCommandHandler)
    unblock_user_handler = provide(UnblockUserCommandHandler)

    @decorate
    def register_profile_command_handlers(self, command_registry: CommandRegistry) -> CommandRegistry:

        command_registry.register_command(
            CreateProfileCommand, CreateProfileCommandHanler
        )
        command_registry.register_command(
            GetOrCreateProfileCommand, GetOrCreateProfileCommandHanler
        )
        command_registry.register_command(
            UpdateProfileCommand, UpdateProfileCommandHandler
        )
        command_registry.register_command(
            UpdateProfileAvatarCommand, UpdateProfileAvatarCommandHandler
        )
        command_registry.register_command(
            ProccessAvatarCommand, ProccessAvatarCommandHandler
        )
        command_registry.register_command(
            AddLinkToProfileCommand, AddLinkToProfileCommandHandler
        )
        command_registry.register_command(
            RemoveLinkFromProfileCommand, RemoveLinkFromProfileCommandHandler
        )
        command_registry.register_command(
            AddContactCommand, AddContactCommandHandler
        )
        command_registry.register_command(
            RemoveContactCommand, RemoveContactCommandHandler
        )
        command_registry.register_command(
            UpdateContactCommand, UpdateContactCommandHandler
        )
        command_registry.register_command(
            ImportContactsCommand, ImportContactsCommandHandler
        )
        command_registry.register_command(
            RegisterUserIdentifierCommand, RegisterUserIdentifierCommandHandler
        )
        command_registry.register_command(
            BlockUserCommand, BlockUserCommandHandler
        )
        command_registry.register_command(
            UnblockUserCommand, UnblockUserCommandHandler
        )

        return command_registry


    @decorate
    def register_profile_event_handlers(self, event_registry: EventRegistry) -> EventRegistry:
        return event_registry

    get_by_id_profile_handler = provide(GetProfileByIdQueryHandler)
    get_profiles_handler = provide(GetProfilesQueryHandler)
    get_upload_url_avatra_handler = provide(GetAvatrProfileUrlQueryHandler)
    get_contacts_handler = provide(GetContactsQueryHandler)
    search_contacts_handler = provide(SearchContactsQueryHandler)
    get_blocked_users_handler = provide(GetBlockedUsersQueryHandler)

    @decorate
    def register_profile_query_handlers(self, query_registry: QueryRegistry) -> QueryRegistry:

        query_registry.register_query(
            GetProfileByIdQuery, GetProfileByIdQueryHandler
        )
        query_registry.register_query(
            GetProfilesQuery, GetProfilesQueryHandler
        )
        query_registry.register_query(
            GetAvatrProfileUrlQuery, GetAvatrProfileUrlQueryHandler
        )
        query_registry.register_query(
            GetContactsQuery, GetContactsQueryHandler
        )
        query_registry.register_query(
            SearchContactsQuery, SearchContactsQueryHandler
        )
        query_registry.register_query(
            GetBlockedUsersQuery, GetBlockedUsersQueryHandler
        )

        return query_registry

    @decorate
    def bucket_policy(self, policy: dict[str, Policy]) -> dict[str, Policy]:
        policy[profile_config.AVATAR_BUCKET] = Policy.GET
        policy[profile_config.PENDING_AVATAR_BUCKET] = Policy.GET
        return policy
