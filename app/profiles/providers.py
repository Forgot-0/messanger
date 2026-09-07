from dishka import Provider, Scope, decorate, provide

from app.core.events.event import EventRegistry
from app.core.mediators.base import CommandRegistry, QueryRegistry
from app.core.services.storage.aminio.policy import Policy
from app.profiles.commands.profiles.add_contact import AddContactToProfileCommand, AddContactToProfileCommandHandler
from app.profiles.commands.profiles.create import CreateProfileCommand, CreateProfileCommandHanler
from app.profiles.commands.profiles.get_or_create import GetOrCreateProfileCommand, GetOrCreateProfileCommandHanler
from app.profiles.commands.profiles.proccess_avatar import ProccessAvatarCommand, ProccessAvatarCommandHandler
from app.profiles.commands.profiles.remove_contact import (
    RemoveContactToProfileCommand,
    RemoveContactToProfileCommandHandler,
)
from app.profiles.commands.profiles.update import UpdateProfileCommand, UpdateProfileCommandHandler
from app.profiles.commands.profiles.update_avatar import UpdateProfileAvatarCommand, UpdateProfileAvatarCommandHandler
from app.profiles.config import profile_config
from app.profiles.queries.profiles.get_by_id import GetProfileByIdQuery, GetProfileByIdQueryHandler
from app.profiles.queries.profiles.get_list import GetProfilesQuery, GetProfilesQueryHandler
from app.profiles.queries.profiles.get_url import GetAvatrProfileUrlQuery, GetAvatrProfileUrlQueryHandler
from app.profiles.repositories.profiles import ProfileRepository


class ProfileModuleProvider(Provider):
    scope = Scope.REQUEST

    profile_repository = provide(ProfileRepository)


    create_profile_handler = provide(CreateProfileCommandHanler)
    update_profile_handler = provide(UpdateProfileCommandHandler)
    update_avatar_profile_handler = provide(UpdateProfileAvatarCommandHandler)
    process_avatar_handler = provide(ProccessAvatarCommandHandler)
    add_contact_profile_handler = provide(AddContactToProfileCommandHandler)
    remove_contact_profile_handler = provide(RemoveContactToProfileCommandHandler)
    get_or_create_provider = provide(GetOrCreateProfileCommandHanler)

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
            AddContactToProfileCommand, AddContactToProfileCommandHandler
        )
        command_registry.register_command(
            RemoveContactToProfileCommand, RemoveContactToProfileCommandHandler
        )

        return command_registry


    @decorate
    def register_profile_event_handlers(self, event_registry: EventRegistry) -> EventRegistry:
        return event_registry

    get_by_id_profile_handler = provide(GetProfileByIdQueryHandler)
    get_profiles_handler = provide(GetProfilesQueryHandler)
    get_upload_url_avatra_handler = provide(GetAvatrProfileUrlQueryHandler)

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

        return query_registry

    @decorate
    def bucket_policy(self, policy: dict[str, Policy]) -> dict[str, Policy]:
        policy[profile_config.AVATAR_BUCKET] = Policy.GET
        policy[profile_config.PENDING_AVATAR_BUCKET] = Policy.GET
        return policy
