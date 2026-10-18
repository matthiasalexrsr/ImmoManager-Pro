"""Public errors and boundaries shared by account-backed assistant transports."""


class ProviderError(RuntimeError):
    def __init__(self, message: str, code: str = "provider_error", *, uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain
