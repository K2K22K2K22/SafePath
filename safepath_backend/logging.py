import logging
import re
import traceback

_URL_QUERY = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://[^\s?\"']+)\?[^\r\n]*")
_PATH_QUERY = re.compile(r"(/[^\s?\"']*)\?[^\r\n]*")
_URL_USERINFO = re.compile(r"(://)[^/@\s]+@")
_AUTHORIZATION = re.compile(
    r"(?i)(?P<prefix>[\"']?authorization[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|(?:(?:Basic|Bearer)\s+)?[^\s]+)"
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9_])"
    r"([A-Za-z0-9_-]*(?:password|passwd|secret(?:_key)?|token|api[_-]?key|auth|q))"
    r"\s*[=:]\s*[^&\s\"']+"
)


def redact_query_values(message):
    message = _URL_QUERY.sub(r"\1", message)
    message = _PATH_QUERY.sub(r"\1", message)
    message = _URL_USERINFO.sub(r"\1[redacted]@", message)
    message = _AUTHORIZATION.sub(
        lambda match: f"{match.group('prefix')}[redacted]",
        message,
    )
    return _SENSITIVE_ASSIGNMENT.sub(r"\1=[redacted]", message)


class SafeLogFormatter(logging.Formatter):
    def formatMessage(self, record):
        message = super().formatMessage(record)
        if record.exc_info and record.exc_info[1] is not None:
            exception_text = str(record.exc_info[1])
            if exception_text:
                message = message.replace(exception_text, "[details redacted]")
        return redact_query_values(message)

    def formatException(self, exc_info):
        lines = ["Traceback (most recent call last):\n"]
        lines.extend(
            f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
            for frame in traceback.extract_tb(exc_info[2])
        )
        lines.append(f"{exc_info[0].__name__}: [details redacted]\n")
        return redact_query_values("".join(lines))
