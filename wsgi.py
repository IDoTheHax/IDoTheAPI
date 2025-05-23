import logging
from logging.handlers import RotatingFileHandler
from api import app

# Configure logging
def setup_logging():
    logger = logging.getLogger('gunicorn.error')  # Hook into Gunicorn's error logger
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        log_format = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        file_handler = RotatingFileHandler(
            'app.log',
            maxBytes=5 * 1024 * 1024,
            backupCount=5
        )
        file_handler.setFormatter(log_format)
        file_handler.setLevel(logging.DEBUG)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_format)
        console_handler.setLevel(logging.INFO)

        # Add handlers to Gunicorn's logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        # Also configure the access logger
        access_logger = logging.getLogger('gunicorn.access')
        access_logger.handlers = []
        access_logger.setLevel(logging.INFO)
        access_logger.addHandler(file_handler)
        access_logger.addHandler(console_handler)

    # Set up the app logger
    app_logger = logging.getLogger('IDoTheLogger')
    app_logger.setLevel(logging.DEBUG)
    app_logger.handlers = logger.handlers  # Share handlers with Gunicorn logger

    return app_logger

# Set up the logger
logger = setup_logging()

# Replace Flask's logger with custom
app.logger.handlers = []
app.logger.propagate = False
app.logger.setLevel(logging.DEBUG)
for handler in logger.handlers:
    app.logger.addHandler(handler)

app.logger.info("Starting the Flask application with Gunicorn")

if __name__ == "__main__":
    app.run(debug=True)
