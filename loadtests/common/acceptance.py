"""
"Acceptance-критерии как код" (п.4 промпта): сценарий должен явно падать
(ненулевой exit code) при превышении порогов, и опираться ТОЛЬКО на
статистику самого Locust (response_time percentiles, fail_ratio, num_requests
из stats API) — никаких внешних метрик/Prometheus.

Пороги — это argparse-параметры (см. add_threshold_arg), а не константы в
коде: значения по умолчанию ниже — намеренно "мягкие" ориентиры для самого
первого прогона (baseline ещё не снят), их нужно пересмотреть по факту первого
запуска и передавать явно через --*-threshold-* в последующих прогонах.

Используется одинаково всеми тремя сценариями (rest_throughput.py,
ws_fanout.py, ws_churn.py), каждый из которых регистрирует СВОИ пороги под
СВОИМИ именами запросов.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from locust.env import Environment
    from locust.stats import RequestStats

Metric = Literal["p95_ms", "p99_ms", "error_rate", "min_requests"]


@dataclass(frozen=True, slots=True)
class Threshold:
    label: str
    request_name: str
    request_method: str
    metric: Metric
    limit: float

    def describe_limit(self) -> str:
        if self.metric in ("p95_ms", "p99_ms"):
            return f"<= {self.limit:.0f} ms"
        if self.metric == "error_rate":
            return f"<= {self.limit * 100:.2f} %"
        return f">= {self.limit:.0f} requests"


def _entry(stats: "RequestStats", t: Threshold):
    return stats.entries.get((t.request_name, t.request_method))


def evaluate_thresholds(stats: "RequestStats", thresholds: list[Threshold]) -> list[str]:
    """Возвращает список сообщений о нарушениях. Пустой список = все пороги пройдены."""
    failures: list[str] = []

    for t in thresholds:
        entry = _entry(stats, t)
        if entry is None or entry.num_requests == 0:
            failures.append(
                f"[{t.label}] нет ни одного запроса '{t.request_method} {t.request_name}' — "
                f"порог '{t.describe_limit()}' не может быть проверен (сценарий не выполнялся "
                f"или название запроса не совпадает)"
            )
            continue

        if t.metric == "p95_ms":
            value = entry.get_response_time_percentile(0.95)
            if value > t.limit:
                failures.append(f"[{t.label}] p95={value:.0f}ms, порог {t.describe_limit()}")
        elif t.metric == "p99_ms":
            value = entry.get_response_time_percentile(0.99)
            if value > t.limit:
                failures.append(f"[{t.label}] p99={value:.0f}ms, порог {t.describe_limit()}")
        elif t.metric == "error_rate":
            rate = entry.num_failures / entry.num_requests
            if rate > t.limit:
                failures.append(
                    f"[{t.label}] error_rate={rate * 100:.2f}% "
                    f"({entry.num_failures}/{entry.num_requests}), порог {t.describe_limit()}"
                )
        elif t.metric == "min_requests":
            if entry.num_requests < t.limit:
                failures.append(
                    f"[{t.label}] всего {entry.num_requests} запросов, порог {t.describe_limit()} "
                    f"(похоже, сценарий не успел толком запуститься — увеличьте -t/--run-time)"
                )

    return failures


def add_threshold_arg(
    parser: argparse.ArgumentParser,
    flag: str,
    default: float,
    help_text: str,
) -> None:
    parser.add_argument(
        flag,
        type=float,
        default=default,
        help=f"{help_text} (по умолчанию: {default}; ПЕРЕСМОТРИТЕ после первого прогона)",
    )


def check_and_report(environment: "Environment", thresholds: list[Threshold]) -> None:
    """Вызывается из @events.quitting.add_listener в каждом locustfile."""
    print("\n" + "=" * 78)
    print("ACCEPTANCE CHECK (источник данных — только Locust stats, см. loadtests/README.md)")
    print("=" * 78)

    if environment.stats is None:
        print("Нет статистики (0 запросов?) — считаю прогон проваленным.")
        environment.process_exit_code = 1
        return

    failures = evaluate_thresholds(environment.stats, thresholds)

    if not failures:
        for t in thresholds:
            print(f"  PASS  [{t.label}] порог {t.describe_limit()}")
        print("Все пороги пройдены.")
        return

    for msg in failures:
        print(f"  FAIL  {msg}")
    print(f"\n{len(failures)} порог(ов) нарушено. Прогон помечается как FAILED (exit code != 0).")
    environment.process_exit_code = 1
