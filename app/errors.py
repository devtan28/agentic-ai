class AppError(Exception):
    """Base class for all application-level errors."""
    pass


class ClientError(AppError):
    """Errors caused by invalid client input."""
    pass


class OperationalError(AppError):
    """Errors caused by external systems or environment."""
    pass
