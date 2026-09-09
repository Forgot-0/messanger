import asyncio
import logging

from app.chats.config import chat_config
from app.chats.services.read_coalescer import ReadReceiptCoalesceQueue
from app.chats.services.read_flusher import ReadReceiptFlusher

logger = logging.getLogger(__name__)


async def run_read_receipt_coalescer(container, queue: ReadReceiptCoalesceQueue) -> None:
    tick = chat_config.READ_RECEIPTS_COALESCE_TICK_MS / 1000

    while True:
        try:
            cursors = await queue.claim_due()

            if cursors:

                try:
                    async with container() as request_container:
                        flusher: ReadReceiptFlusher = await request_container.get(
                            ReadReceiptFlusher
                        )
                        await flusher.flush(cursors)
                except Exception:
                    await queue.requeue(cursors)
                    raise

        except asyncio.CancelledError:
            logger.info("Read receipt coalescer stopping")
            raise
        except Exception:
            logger.exception("Read receipt coalescer tick failed")

        await asyncio.sleep(tick)
