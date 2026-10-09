class PrepError(Exception):
    """User-facing failure. The message is safe to show in the UI."""


class PrepCancelled(Exception):
    """The user cancelled this job."""
