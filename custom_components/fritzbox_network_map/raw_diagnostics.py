"""Consistent, DEBUG-only logging of raw FRITZ!Box source data."""

from __future__ import annotations

import json
import logging

_MAX_LOG_CHARS = 50000

def log_raw_diagnostic(logger: logging.Logger, source: str, payload) -> None:
    """Log a raw response only when DEBUG is enabled, with a bounded size.

    Raw data can contain local hostnames, IP addresses and MAC addresses.
    It is therefore deliberately never emitted at INFO/WARNING level.
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return
    if isinstance(payload, str):
        rendered = payload
    else:
        try:
            rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            rendered = repr(payload)
    truncated = len(rendered) > _MAX_LOG_CHARS
    if truncated:
        rendered = rendered[:_MAX_LOG_CHARS] + "\n... [abgeschnitten; Rohdatenlimit 50000 Zeichen]"
    logger.debug("FRITZ!Box ROHDATEN [%s]%s\n%s", source, " (gekürzt)" if truncated else "", rendered)
