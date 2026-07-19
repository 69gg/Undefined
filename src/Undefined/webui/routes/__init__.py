from ._shared import routes

__all__ = ["routes"]
from . import (  # noqa: F401  register handlers
    _auth,
    _bot,
    _config,
    _index,
    _logs,
    _memes,
    _runtime,
    _system,
    _weixin,
)
