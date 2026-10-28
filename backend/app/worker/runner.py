import logging
import signal
from threading import Event
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine, get_session_factory
from app.api.dependencies import make_runtime
from app.worker.worker import ClickWorker


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    stop_event = Event()
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop_event.set())
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop_event.set())
    # The worker's blocking XREADGROUP timeout must be shorter than Redis' socket timeout.
    worker_socket_timeout = max(settings.redis_socket_timeout_seconds, settings.worker_block_ms / 1000 + 0.5)
    runtime = make_runtime(settings, socket_timeout_seconds=worker_socket_timeout)
    worker = ClickWorker(runtime.redis, get_session_factory(), settings)
    logging.getLogger(__name__).info("click_worker_started", extra={"consumer": worker.consumer})
    try:
        worker.run_forever(stop_event)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("click_worker_stopping")
    finally:
        runtime.redis.close()
        dispose_engine()


if __name__ == "__main__":
    main()
