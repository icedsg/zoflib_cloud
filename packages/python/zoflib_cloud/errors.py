"""Normalized errors (spec/errors.json). Messages never carry credentials, headers, signed URLs or response bodies."""
import re

CODES = ("authentication", "permission", "not_found", "conflict", "confirmation_required", "throttled", "quota",
         "invalid_config", "network", "cancelled", "unsupported", "provider_error")
RETRYABLE = ("throttled", "network", "provider_error")
CONTRACT_VERSION = "0.1.0"

_PATTERNS = [(re.compile(r"X-Amz-[A-Za-z-]+=[^&\s]+", re.I), "X-Amz-...=<redacted>"),
             (re.compile(r"(?i)(authorization:\s*)\S+(\s+\S+)*"), r"\1<redacted>"),
             (re.compile(r"AKIA[0-9A-Z]{16}"), "<redacted>")]


def redact(text):
    text = str(text)
    for pat, rep in _PATTERNS: text = pat.sub(rep, text)
    return text


class CloudError(Exception):
    def __init__(self, code, message="", provider_code=None, request_id=None, retry_after_ms=None):
        if code not in CODES: raise ValueError("unknown error code " + str(code))
        super().__init__(redact(message))
        self.code, self.provider_code, self.request_id, self.retry_after_ms = code, provider_code, request_id, retry_after_ms

    @property
    def retry(self):
        return self.code in RETRYABLE

    def to_dict(self):
        d = {"code": self.code, "message": str(self)}
        for k in ("provider_code", "request_id", "retry_after_ms"):
            if getattr(self, k) is not None: d[k] = getattr(self, k)
        return d


class CancelToken:
    def __init__(self): self.cancelled = False
    def cancel(self): self.cancelled = True

    def check(self):
        if self.cancelled: raise CloudError("cancelled", "operation cancelled")
