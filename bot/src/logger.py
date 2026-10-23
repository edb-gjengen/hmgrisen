import logging
import logging.handlers
import os
import sys


class BotLogger:
    """Logging config for the bot"""

    def __init__(self):
        logger = logging.getLogger("")
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "[{asctime}] [{levelname:<8}] {name} - [{filename}] - [{funcName}] - {message}",
            "%Y-%m-%d %H:%M:%S",
            style="{",
        )

        if not os.path.exists("logs"):
            os.makedirs("logs")

        # Appends, so a restart doesn't overwrite the log. Rotated at midnight, and old logs are kept
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename="logs/bot.log",
            when="midnight",
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler(sys.stdout)  # level is INFO we use stdout instead of stderr
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        self.logger = logger
