import warnings

from .api import Gino
from .pool import GinoPool
from .connection import GinoConnection
from .local import (
    enable_task_local as enable_connection_reuse,
    disable_task_local as disable_connection_reuse,
    reset_local as forget_connection,
)
from .exceptions import *


def get_local():
    warnings.warn(
        'gino.get_local is deprecated, please use gino.local.get_local',
        PendingDeprecationWarning, stacklevel=2)
    from .local import get_local
    return get_local()


def enable_task_local(loop=None):
    warnings.warn(
        'gino.enable_task_local is deprecated, '
        'please use gino.enable_connection_reuse',
        PendingDeprecationWarning, stacklevel=2)
    return enable_connection_reuse(loop)


def disable_task_local(loop=None):
    warnings.warn(
        'gino.disable_task_local is deprecated, '
        'please use gino.disable_connection_reuse',
        PendingDeprecationWarning, stacklevel=2)
    return disable_connection_reuse(loop)


__version__ = '0.5.4'
