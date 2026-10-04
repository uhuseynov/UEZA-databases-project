import logging
import sys

from pythonjsonlogger.json import JsonFormatter

from config import Settings


class AppLogger:
    """
    AppLogger is a utility class for configuring and managing application-wide logging.

    This class provides a mechanism to set up a logger instance with customizable settings
    and formats based on the application's environment. It supports both JSON-formatted logs
    for production environments and human-readable logs for other environments. The logger
    is designed to avoid duplicate handlers and ensures proper configuration of log levels
    and output formats.

    Attributes:
        settings (Settings): An instance of the `Settings` class containing configuration
            options such as `log_level` and `app_env`.

    Methods:
        __init__(settings: Settings):
            Initializes the AppLogger instance with the provided settings.

        setup():
            Sets the logging level and output format based on the application environment.

        get_logger(name: str) -> logging.Logger:
            Retrieves a logger instance with the specified name.
    """

    def __init__(self, settings: Settings):
        """
        Initializes the logger with the provided settings.

        Args:
            settings (Settings): The configuration settings for the logger.
        """
        self.settings = settings
        self.logger = logging.getLogger()

    def setup(self):
        """
        Configures the logger instance with the appropriate settings and formatters.

        This method sets the logging level based on the `log_level` attribute from the settings.
        It also configures the log output format depending on the application environment:
        - In "production" environment, logs are formatted in JSON.
        - In other environments, logs are formatted in a human-readable format.

        The method ensures that duplicate log handlers are avoided by clearing existing handlers
        before adding a new one.
        """
        self.logger.setLevel(self.settings.log_level.upper())

        handler = logging.StreamHandler(sys.stdout)

        if self.settings.app_env.lower() == "production":
            #  JSON format
            formatter = JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s %(filename)s")
        else:
            # Human-readable format
            formatter = logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s]: %(message)s")

        handler.setFormatter(formatter)

        # Reset handlers to avoid duplicate logs
        if self.logger.hasHandlers():
            self.logger.handlers.clear()
        self.logger.addHandler(handler)

    def get_logger(self, name: str) -> logging.Logger:
        """
        Retrieve a logger instance with the specified name.

        This method provides a convenient way to obtain a logger
        for logging messages in the application. The logger can
        be used to log messages at various severity levels such as
        DEBUG, INFO, WARNING, ERROR, and CRITICAL.

        Args:
            name (str): The name of the logger to retrieve. Typically,
                        this is the name of the module or component
                        where the logger is used.

        Returns:
            logging.Logger: A logger instance associated with the given name.
        """
        return logging.getLogger(name)
