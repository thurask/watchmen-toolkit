"""extract_out -- the test every command that reads an extract output makes first.

An EXTRACT_OUT is the folder `watchmen extract NAZ OUT` writes; it always holds an
`extracted/` folder (the raw asset tree).  A command given another folder -- a typo, the
game folder, the character export -- would read nothing and write empty tables with exit
code 0, so it stops instead (the CLI prints the message and exits with 2).
"""

import os


def is_extract_out(path):
    """Does `path` look like an extract output (it has an `extracted/` folder)?"""
    return bool(path) and os.path.isdir(os.path.join(str(path), "extracted"))


def require(path):
    """Raise FileNotFoundError unless `path` is an extract output; returns `path`."""
    if not is_extract_out(path):
        raise FileNotFoundError(
            "%s is not an extract output (no extracted/ folder): run `watchmen extract NAZ %s`"
            " first, or name the folder that `extract` wrote" % (path, path)
        )
    return path
