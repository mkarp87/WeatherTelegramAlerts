from __future__ import annotations

import argparse
import logging
import sys
import threading
from typing import Any

from .config import BASE_DIR, as_bool, load_config
from .poller import main_iteration, setup_logging
from .web import create_app

LOGGER = logging.getLogger(__name__)


def poller_loop(config_path: str, stop_event: threading.Event) -> None:
    """Run the Telegram/NWS poller inside the web process."""
    LOGGER.info("Starting embedded Telegram/NWS poller")
    while not stop_event.is_set():
        try:
            config = load_config(config_path)
            setup_logging(config)
            interval = int(config.get("WeatherAlerts", {}).get("PollInterval", 300) or 300)
            main_iteration(config)
        except Exception as exc:
            LOGGER.exception("Unhandled poller exception: %s", exc)
            try:
                config = load_config(config_path)
                interval = int(config.get("WeatherAlerts", {}).get("PollInterval", 300) or 300)
            except Exception:
                interval = 300
        stop_event.wait(max(30, int(interval)))
    LOGGER.info("Embedded poller stopped")


def start_poller(config_path: str) -> tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=poller_loop,
        args=(config_path, stop_event),
        name="weather-alerts-poller",
        daemon=True,
    )
    thread.start()
    return stop_event, thread


def run_server(*, app: Any, host: str, port: int, waitress: bool) -> None:
    if waitress:
        from waitress import serve

        serve(app, host=host, port=port)
    else:
        app.run(host=host, port=port, debug=False, use_reloader=False)


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WeatherTelegramAlerts unified service")
    parser.add_argument("-c", "--config", default=str(BASE_DIR / "config.yaml"), help="Path to YAML config file")
    parser.add_argument("-p", "--port", type=int, default=None, help="Port to run the web server on")
    parser.add_argument("--host", default=None, help="Host/IP to bind")
    parser.add_argument("--waitress", action="store_true", help="Force the Waitress WSGI server; otherwise Webapp.Waitress controls this")
    parser.add_argument("--no-poller", action="store_true", help="Run only the web dashboard")
    parser.add_argument("--once", action="store_true", help="Run one polling iteration and exit")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    setup_logging(config)

    if args.once:
        main_iteration(config)
        return 0

    web_cfg = config.get("Webapp", {}) or {}
    host = args.host or web_cfg.get("Host", "127.0.0.1")
    port = int(args.port or web_cfg.get("Port", 8085) or 8085)
    use_waitress = bool(args.waitress or as_bool(web_cfg.get("Waitress"), default=True))

    app = create_app(args.config)
    stop_event: threading.Event | None = None
    poller_thread: threading.Thread | None = None

    if not args.no_poller:
        stop_event, poller_thread = start_poller(args.config)

    LOGGER.info("Starting unified WeatherTelegramAlerts service on %s:%s", host, port)
    try:
        run_server(app=app, host=str(host), port=port, waitress=use_waitress)
    except KeyboardInterrupt:
        LOGGER.info("Interrupted; exiting")
    finally:
        if stop_event is not None:
            stop_event.set()
        if poller_thread is not None:
            poller_thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(cli())
