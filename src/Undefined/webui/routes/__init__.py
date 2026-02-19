from ._shared import routes

__all__ = ["routes"]
from . import _index, _auth, _bot, _config, _logs, _system  # noqa: F401  register handlers
