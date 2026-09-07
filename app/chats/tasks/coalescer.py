import asyncio
import logging

from app.chats.config import chat_config
from app.chats.metrics import CHAT_REACTION_COALESCE_COLLAPSED
from app.chats.services.delivery_router import ChatDeliveryRouter
from app.chats.services.reaction_coalescer import ReactionCoalesceQueue

logger = logging.getLogger(__name__)


async def run_reaction_coalescer(container, queue: ReactionCoalesceQueue) -> None:
    tick = chat_config.REACTIONS_COALESCE_TICK_MS / 1000

    while True:
        try:
            snapshots = await queue.claim_due()

            if snapshots:
                CHAT_REACTION_COALESCE_COLLAPSED.observe(len(snapshots))

                async with container() as request_container:
                    router: ChatDeliveryRouter = await request_container.get(ChatDeliveryRouter)
                    for snapshot in snapshots:
                        await router.route_reaction_snapshot(snapshot)

        except asyncio.CancelledError:
            logger.info("Reaction coalescer stopping")
            raise
        except Exception:
            logger.exception("Reaction coalescer tick failed")

        await asyncio.sleep(tick)
