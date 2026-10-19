"""Dependency-free error identities for provider and worker boundaries."""


class DataError(ValueError):
    code = 'DATA_INVALID'


class ProviderError(RuntimeError):
    code = 'PROVIDER_UNAVAILABLE'
