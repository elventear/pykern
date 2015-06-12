# -*- coding: utf-8 -*-
u"""Python 2 and 3 compatbility routines

:mod:`six` and :mod:`future.utils` do most things, but there are some missing
things here

:copyright: Copyright (c) 2015 Bivio Software, Inc.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function, unicode_literals
from io import open

import inspect
import locale
import os
import subprocess


def locale_check_output(*args, **kwargs):
    """Convert subprocess output to unicode in the preferred locale.

    Returns:
        str: decoded string (PY2: type unicode)
    """
    return locale_str(subprocess.check_output(*args, **kwargs))


def locale_str(value):
    """Converts a value to a unicode str unless already unicode.

    Args:
        value: The string or object to be decoded, may be None.

    Returns:
        str: decoded string (PY2: type unicode)
    """
    if type(value) == unicode:
        return value
    if type(value) not in [bytes, str]:
        value = str(value)
    return value.decode(locale.getpreferredencoding())

if not hasattr(str, 'decode'):
    locale_str = str


def unicode_getcwd():
    """:func:`os.getcwd` unicode wrapper

    Returns:
        str: current directory (PY2: type unicode)
    """
    return os.getcwdu()


if not hasattr(os, 'getcwdu'):
    unicode_getcwd = os.getcwd
