from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.exceptions import AccessDeniedError
from app.core.services.auth.rbac import RBACManagerInterface
from app.profiles.config import profile_config


def check_contact_owner(
    rbac_manager: RBACManagerInterface,
    owner_id: int,
    user_jwt_data: UserJWTData | None,
) -> None:
    """Адресная книга всегда своя: чужую трогает только администратор.

    user_jwt_data is None — вызов изнутри (фоновая задача, консьюмер),
    туда токен не доезжает, а owner_id уже проверен на входе в HTTP.
    """
    if user_jwt_data is None:
        return

    if owner_id == int(user_jwt_data.id):
        return

    required = set(profile_config.CONTACT_OWNER_PERMISSIONS)
    if rbac_manager.check_permission(user_jwt_data, required):
        return

    raise AccessDeniedError(need_permissions=required - set(user_jwt_data.permissions))
