import logging

import firebase_admin
from firebase_admin import App, credentials

logger = logging.getLogger(__name__)


def init_firebase_app(app_name: str, credentials_path: str) -> App:
    try:
        return firebase_admin.get_app(name=app_name)
    except ValueError:
        pass

    cred = credentials.Certificate(credentials_path)
    app = firebase_admin.initialize_app(credential=cred, name=app_name)
    logger.info("Firebase app initialized", extra={"app_name": app_name})
    return app

