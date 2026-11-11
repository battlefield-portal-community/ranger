"""Trust the CA bundle certifi ships.

aiohttp — and therefore discord.py — builds its TLS context with
``ssl.create_default_context()``, which trusts whatever bundle the interpreter's
OpenSSL was built with. python.org's macOS builds and some slim images ship none,
so HTTPS to Discord fails with ``CERTIFICATE_VERIFY_FAILED`` while pip (which uses
certifi) works fine. Naming certifi's bundle in ``SSL_CERT_FILE`` fixes every client
in the process; a deployment that already sets it, or a distro that populates the
default store, keeps its own.
"""

from __future__ import annotations

import logging
import os

import certifi

log = logging.getLogger(__name__)


def use_certifi() -> str | None:
    """Trust certifi's bundle unless the environment already names one.

    Returns the bundle path when this call set it, else None.
    """
    if os.environ.get("SSL_CERT_FILE"):
        return None
    bundle = certifi.where()
    os.environ["SSL_CERT_FILE"] = bundle
    log.debug("Trusting the CA bundle from certifi: %s", bundle)
    return bundle
