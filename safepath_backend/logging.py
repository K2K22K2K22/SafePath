import logging
import re
import traceback

_URL_QUERY = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://[^\s?\"']+)\?[^\s\"']+")
_PATH_QUERY = re.compile(r"(/[^\s?\"']*)\?[^\s\"']+")


def redact_query_values(message):
    message = _URL_QUERY.sub(r"\1", message)
    return _PATH_QUERY.sub(r"\1", message)


class SafeLogFormatter(logging.Formatter):
    def formatMessage(self, record):
        return redact_query_values(super().formatMessage(record))

    def formatException(self, exc_info):
        lines = ["Traceback (most recent call last):\n"]
        lines.extend(
            f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
            for frame in traceback.extract_tb(exc_info[2])
        )
        lines.append(f"{exc_info[0].__name__}: [details redacted]\n")
        return redact_query_values("".join(lines))
