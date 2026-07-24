"""wlib — extraction library for Watchmen: The End Is Nigh (Kapow engine).

The modules in this package were developed as flat top-level modules that
import each other directly (``import watchmen_extract``, ...).  Importing
this package puts the package directory on ``sys.path`` so those flat
imports keep working unchanged, whether the package is used from a source
checkout or a pip install.

Typical entry points:

    import wlib                       # enables the flat sibling imports
    import watchmenlib as wl          # the facade: one import for everything
    wl.extract_all('game.naz', 'OUT')

or just use the ``watchmen`` command-line tool (see ``watchmen --help``).
"""

import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:
    # APPEND, never insert(0): these are flat, generic module names (char_lib,
    # gen_data, engine_schema, ...) and must not shadow the stdlib or any other
    # installed package for the rest of the host process.
    _sys.path.append(_HERE)

__version__ = "1.1.0"
