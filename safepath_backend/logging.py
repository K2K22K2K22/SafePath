import logging
import re
import traceback

_URL_QUERY = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://[^\s?\"']+)\?[^\s\"']+")
_PATH_QUERY = re.compile(r"(/[^\s?\"']*)\?[^\s\"']+")
_URL_USERINFO = re.compile(r"(://)[^/@\s]+@")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret(?:_key)?|token|api[_-]?key|authorization|auth|q)"
    r"\s*[=:]\s*[^&\s\"']+"
)


def redact_query_values(message):
    message = _URL_QUERY.sub(r"\1", message)
    message = _PATH_QUERY.sub(r"\1", message)
    message = _URL_USERINFO.sub(r"\1[redacted]@", message)
    return _SENSITIVE_ASSIGNMENT.sub(r"\1=[redacted]", message)


class SafeLogFormatter(logging.Formatter):
    def formatMessage(self, record):
        message = redact_query_values(super().formatMessage(record))
        if record.exc_info and record.exc_info[1] is not None:
            if message == str(record.exc_info[1]):
                return "[details redacted]"
        return message

    def formatException(self, exc_info):
        lines = ["Traceback (most recent call last):\n"]
        lines.extend(
            f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
            for frame in traceback.extract_tb(exc_info[2])
        )
        lines.append(f"{exc_info[0].__name__}: [details redacted]\n")
        return redact_query_values("".join(lines))
