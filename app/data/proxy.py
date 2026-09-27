"""Used only inside the isolated AKShare worker, never API/CLI parent threads."""
from contextlib import contextmanager


@contextmanager
def ignore_inherited_proxies():
    """Ignore environment/Windows proxy lookup; retain TLS and other settings.

    No environment variable, registry key, global Windows setting or VPN changes.
    Both Requests lookup paths (initial request and redirects) are restored even
    if the direct request fails. The worker is disposable and single-purpose.
    """
    import requests.sessions
    import requests.utils
    session_lookup = requests.sessions.get_environ_proxies
    utility_lookup = requests.utils.get_environ_proxies
    try:
        requests.sessions.get_environ_proxies = lambda *a, **kw: {}
        requests.utils.get_environ_proxies = lambda *a, **kw: {}
        yield
    finally:
        requests.sessions.get_environ_proxies = session_lookup
        requests.utils.get_environ_proxies = utility_lookup


def call_with_proxy_fallback(call):
    import requests
    try:
        return call(), {'network_mode': 'normal', 'network_attempts': 1}
    except requests.exceptions.ProxyError:
        with ignore_inherited_proxies():
            try:
                return call(), {'network_mode': 'direct_after_proxy_error', 'network_attempts': 2}
            except Exception as exc:
                from app.data.models import ProviderError
                error = ProviderError(f'代理路径失败：ProxyError；临时直连失败：{type(exc).__name__}')
                error.retryable = False  # Two actual attempts; do not multiply outer retries.
                raise error from exc
