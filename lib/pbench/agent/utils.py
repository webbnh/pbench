import logging
import os

import colorlog


def setup_logging(name=None, debug=False, logfile=None):
    """Setup logging for client
    :param None: name of the python object
    :param debug: Turn on debug logging
    :param logfile: Logfile to write to
    """
    if not name:
        log = logging.getLogger()  # root logger
    else:
        log = logging.getLogger(name)

    # Make sh logging a bit less verbose
    logging.getLogger("sh").setLevel(logging.WARNING)

    # FIXME: since we dont do debugging level yet
    log.setLevel(logging.INFO)

    format_str = "%(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    cformat = "%(log_color)s" + format_str
    colors = {
        "DEBUG": "green",
        "INFO": "cyan",
        "WARNING": "bold_yellow",
        "ERROR": "bold_red",
        "CRITICAL": "bold_purple",
    }
    # Setup console
    formatter = colorlog.ColoredFormatter(cformat, date_format, log_colors=colors)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    # Setup log file
    if logfile is not None:
        if not os.environ.get("_PBENCH_UNIT_TESTS"):
            format_str = "[%(levelname)-1s][%(asctime)s.%(msecs)d] %(message)s"
        else:
            format_str = "[%(levelname)-1s][1900-01-01T00:00:00.000000] %(message)s"

        _formatter = logging.Formatter(format_str)
        log_file = logging.FileHandler(logfile)
        log_file.setLevel(logging.DEBUG)
        log_file.setFormatter(_formatter)
        log.addHandler(log_file)

    log.addHandler(stream_handler)

    return log