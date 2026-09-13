import logging


# Set up one consistent log format for every entry point (API, worker, command-line tools),
# so log lines from different processes look the same and are easy to search.
def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
