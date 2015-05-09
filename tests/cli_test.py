# -*- coding: utf-8 -*-
"""pytest for `pykern.cli`

:copyright: Copyright (c) 2015 Bivio Software, Inc.  All Rights Reserved.
:license: Apache, see LICENSE for more details.
"""

import pytest
import re
import sys

from pykern import cli


def test_conformance1():
    """Verify basic modes work"""
    _conf(['conf1', 'cmd1', '1'])
    _conf(['conf1', 'cmd2'], first_time=False)
    _conf(['conf2', 'cmd1', '2'])
    _conf(['conf3', '3'], default_command=True)


def test_deviance1(capsys):
    _dev([], None, r'\nconf1\nconf2\n', capsys)


def test_deviance2(capsys):
    _dev(['conf1'], SystemExit, r'cmd1,cmd2.*too few', capsys)


def test_deviance3(capsys):
    _dev(['not_found'], None, r'no module', capsys)


def _conf(argv, first_time=True, default_command=False):
    full_name = 't_cli.b_cli.' + argv[0]
    if not first_time:
        assert not hasattr(sys.modules, full_name)
    assert _main(argv) == 0, 'Unexpected exit'
    m = sys.modules[full_name]
    if default_command:
        assert m.last_cmd.__name__ == 'default_command'
        assert m.last_arg == argv[1]
    else:
        assert m.last_cmd.__name__ == argv[1]


def _dev(argv, exc, expect, capsys):
    if exc:
        with pytest.raises(exc):
            _main(argv)
    else:
        assert _main(argv) == 1, 'Failed to exit(1): ' + argv
    out, err = capsys.readouterr()
    assert re.search(expect, err, flags=re.IGNORECASE+re.DOTALL), out + err


def _main(argv):
    sys.argv[:] = ['cli_test']
    sys.argv.extend(argv)
    return cli.main('t_cli')
