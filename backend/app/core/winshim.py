"""Windows + Anaconda compatibility shim.

Some Anaconda installs ship a machine-wide ``sitecustomize.py`` that, on Windows,
replaces ``shutil.move`` with a 2-argument ``_safe_move`` (a symlink-permission
workaround). That patched move rejects the ``copy_function`` keyword that
``huggingface_hub`` passes when caching a downloaded model, which breaks
faster-whisper's first-run model download.

``apply()`` re-wraps ``shutil.move`` to tolerate (and ignore) the extra argument,
but only when the active ``shutil.move`` cannot accept ``copy_function``. On a stock
``shutil.move`` (e.g. Linux/production) it is a no-op, so importing this is always
safe. Imported by the transcription service before any model download.
"""
from __future__ import annotations

import inspect
import shutil


def apply() -> bool:
    """Wrap shutil.move if it can't accept copy_function. Returns True if patched."""
    move = shutil.move
    try:
        if "copy_function" in inspect.signature(move).parameters:
            return False  # stock shutil.move — nothing to do
    except (TypeError, ValueError):
        return False  # builtin/uninspectable — assume fine

    def _move_compat(src, dst, *args, **kwargs):
        return move(src, dst)  # drop copy_function (and any extra kwargs)

    shutil.move = _move_compat
    return True


apply()
