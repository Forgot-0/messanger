"""
Клиентский token-bucket для сценария (c): на момент написания теста
rate-limit на WS-командах (resume/subscribe) в приложении ЕЩЁ НЕ РЕАЛИЗОВАН
(промпт 1, п.4) — grep по app/ подтверждает отсутствие RATE_LIMITED в
WS-обработчиках. Поэтому единственный способ не "спалить" ложный вывод вида
"WS resume выдерживает любую частоту" — самим тестом ограничить частоту
resume/subscribe снизу вверх, конфигурируемым параметром, как и просит п.3(c)
промпта: "сделай лимит частоты resume настраиваемым параметром сценария,
чтобы можно было потом просто уменьшить интенсивность без переписывания
скрипта". Когда промпт 1 будет выполнен, этот клиентский лимитер можно будет
поднять выше серверного и honestly замерить уже серверное поведение под
RATE_LIMITED (см. loadtests/README.md).
"""
from __future__ import annotations

import time

import gevent
from gevent.lock import BoundedSemaphore


class TokenBucket:
    """Простой потокобезопасный (в терминах gevent-кооперативности) token bucket."""

    def __init__(self, rate_per_second: float, burst: int | None = None) -> None:
        self.rate = max(rate_per_second, 0.001)
        self.capacity = burst if burst is not None else max(1, int(rate_per_second))
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()
        self._lock = BoundedSemaphore(1)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)

    def acquire(self) -> None:
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait_for = (1 - self._tokens) / self.rate
            gevent.sleep(max(wait_for, 0.01))
