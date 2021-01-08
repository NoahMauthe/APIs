class ConfigurationError(Exception):
    pass


class LoginException(Exception):
    pass


class AuthenticationError(Exception):
    pass


class TokenError(AuthenticationError):
    pass


class RequestError(BaseException):
    pass


class Retry(Exception):
    pass


class Wait(Exception):
    pass


class Maximum(Exception):
    pass
