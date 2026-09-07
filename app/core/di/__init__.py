from dishka import Provider

from app.core.di.auth import AuthServicesProvider
from app.core.di.broker import BrokerProvider
from app.core.di.core import CoreProvider
from app.core.di.db import DBProvider
from app.core.di.events import EventProvider
from app.core.di.mail import MailProvider
from app.core.di.mediator import MediatorProvider
from app.core.di.queues import QueueProvider
from app.core.di.websocket import CoreWSProvider


def get_core_providers() -> list[Provider]:
    return [
        BrokerProvider(),
        DBProvider(),
        CoreProvider(),
        MediatorProvider(),
        EventProvider(),
        QueueProvider(),
        MailProvider(),
        AuthServicesProvider(),
        CoreWSProvider(),
    ]
