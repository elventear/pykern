# -*- coding: utf-8 -*-
"""Declarative module configuration with dynamic value injection

Module Declaration
------------------

Modules declare their configuration via `init`. Here is how `pkdebug`
declares its config params::

    cfg = pkconfig.init(
        control=(None, re.compile, 'Pattern to match against pkdc messages'),
        want_pid_time=(False, bool, 'Display pid and time in messages'),
        output=(None, _cfg_output, 'Where to write messages either as a "writable" or file name'),
    )

A param tuple contains three values:

    0. Default value, in the expected type
    1. Callable that can convert a string or other type into a valid value
    2. A docstring briefly explaining the configuration element

The returned ``cfg`` object is ready to use after the call. It will contain
the config params as defined or an exception will be raised.

Channel Files
-------------

Configuration files are python modules, which define functions for each channel
to be configured. A channel is a stage of deployment. There are four channels:

    dev
        This is the default channel. It's what developers use to configure
        their systems.

    alpha
        The first stage of a deployment. The configuration supports automated
        testing. Customer data is stored on alpha systems.

    beta
        First stage of customer use. The configuration supports both test
        and real users. Since there is customer data, encryption keys
        should be something randomly generated.

    prod
        Production systems contain customer data so they should be
        configured for backups, privacy, and scaling.

The name of the channel is specified by the environment variable
``$PYKERN_PKCONFIG_CHANNEL``. If not set, the channel will be ``dev``.

Config Files
------------

Config modules are found along a load path defined by the
environment variable ``$PYKERN_PKCONFIG_LOAD_PATH`` or set by an
entry point module, e.g. `pykern.pkcli`. The load path consists of
root-level package names (e.g. pykern) to identify configuration modules.

Each package in the load path may contain a ``<pkg>.base_pkconfig.py``,
which will be imported first. All the base_pkconfig modules are loaded
before any other files, and they are imported in the order of the load
path.

Next anay "home files" of the form ``~/.<pkg>_pkconfig.py`` are
imported in the order of the load path.

Once loaded the channel method for each module in the load path are
called. These Each loaded module can override any values. They can
also combine values through formatters (see below).

One last level of configuration is environment values for individual
parameters. If an environment variable exists that matches the upper
case, underscored parameter name, it will override all other values.
For example, you can set ``$PYKERN_PKDEBUG_OUTPUT`` to ``/dev/tty`` if
you want to set the ``output`` parameter for `pykern.pkdebug` so that
pkdebug writes debug output to the terminal.

Config Values
-------------

The values of parameters in config files are specified in nested
dictionaries. The channel function must return a type level dictionary
with the package roots as the first keys, then the submodules, and
which then point to parameters.

Suppose we have ``my_app`` that uses Flask and wants pkdebug to stdout
in development. Here's what ``my_app/base_pkcoonfig.py`` might contain::

    import os
    import sys

    def dev():
        return {
            'my_app': {
                'flask_init': {
                    'db': 'sqlite://' + os.getcwd() + '/my_app.db',
                },
            },
            'pykern': {
                'pkdebug': {
                    'output': sys.stdout,
                },
            },
        }

Configuration is returned as nested dicts. The values themselves could
be any Python object. In this case, we have a string and a file object for the two
parameters. We called `os.getcwd` and referred to `sys.stdout` in param values.

Param values can refer to other param values using `format` values. Suppose there
was a value called ``run_dir``, and we wanted the ``db`` to be stored in that
directory. Here's what the config might look like::

    def dev():
        return {
            'my_app': {
                'flask_init': {
                    'run_dir': py.path.local().join('run'),
                    'db': 'sqlite://{MY_APP_FLASK_INIT_RUN_DIR}/my_app.db',
                },
            },
        }

Formatted values are run through `str.format` until the values stop
changing. All `os.environ` values can be referenced in format string
values as well.  Only string values are resolved with
`str.format`. Other objects are passed verbatim to the parser.
If a value hasn't been parsed, it cannot be referenced in a format
token.

If you want to protect a value from evaluation, you use the `Verbatim`
class as follows::

    def dev():
        return {
            'my_app': {
                'my_templates': {
                    'login': pkconfig.Verbatim('Hello {{user.name}}'),
                },
            },
        }

Summary
-------

Here are the steps to configuring an application:

1. When the first module calls `init`, pkconfig reads all module config
   and environment variables to create a single dict of param values,
   unparsed, by calling `merge` repeatedly.

2. `init` looks for the module's params by indexing with (root_pkg, submodule, param)
   in the merged config.

3. If the parameter is found, that value is used. Else, the default is merged
   into the dict and used.

4. The parameter value is then resolved with `str.format`. If the value
   is a `list` it will be joined with any previous value (e.g. default).

5. The resolved value is parsed using the param's declared ``parser``.

6. The result is stored in the merged config and also stored in the module's
   `Params` object .

7. Once all params have been parsed for the module, `init` returns the `Params`
   object to the module, which can then use those params to initialize itself.

:copyright: Copyright (c) 2015 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html

"""
from __future__ import absolute_import, division, print_function

# Import the minimum number of modules and none from pykern
# pkconfig is the first module imported by all other modules in pykern
import collections
import copy
import importlib
import inspect
import os
import re
import sys

# These modules have very limited imports to avoid loops
from pykern import pkcollections
from pykern import pkinspect
from pykern import pkrunpy

#: Name of the module (required) for a package
BASE_MODULE = '{}.base_pkconfig'

#: Environment variable holding channel (defaults to 'dev')
CHANNEL_ENV_NAME = 'PYKERN_PKCONFIG_CHANNEL'

#: Name of the file to load in user's home directory if exists
HOME_FILE = os.path.join('~', '.{}_pkconfig.py')

#: Validate key: Cannot begin with non-letter or end with an underscore
KEY_RE = re.compile('^[a-z][a-z0-9_]*[a-z0-9]$', flags=re.IGNORECASE)

#: Environment variable holding the load path
LOAD_PATH_ENV_NAME = 'PYKERN_PKCONFIG_LOAD_PATH'

#: Separater for load_path string
LOAD_PATH_SEP = ':'

#: Root package implicit
THIS_PACKAGE = 'pykern'

#: Order of channels from least to most stable
VALID_CHANNELS = ('dev', 'alpha', 'beta', 'prod')

#: Channels which can have more verbose output from the server
INTERNAL_TEST_CHANNELS = VALID_CHANNELS[0:2]

#: Configuration for this module: channel and load_path. Available after first init() call
cfg = None

#: Initialized channel (same as cfg.channel)
CHANNEL_DEFAULT = VALID_CHANNELS[0]

#: Load path default value
LOAD_PATH_DEFAULT = [THIS_PACKAGE]

#: Attribute to detect parser which can parse None
_PARSE_NONE_ATTR = 'pykern_pkconfig_parse_none'

#: Where to load for packages (same as cfg.load_path)
_load_path = LOAD_PATH_DEFAULT

#: All values in _load_path coalesced
_raw_values = None

#: All values parsed via init() and os.environ that don't match loadpath
_parsed_values = None

#: String types, because we can't import modules (e.g. six)
try:
    _string_types = (basestring,)
except NameError:
    _string_types = (str,)


class Verbatim(str, object):
    """Container for string values, which should not be formatted

    Example::

        def dev():
            return {
                'pkg': {
                    'module': {
                        'cfg1': pkconfig.Verbatim('eg. a jinja {{template}}'),
                        'cfg2': 'This string will be formatted',
                    },
                },
            }
    """
    def __format__(self, *args, **kwargs):
        raise AssertionError(
            '{}: you cannot refer to this formatted value'.format(str(self)))


class Required(tuple, object):
    """Container for a required parameter declaration.

    Example::

        cfg = pkconfig.init(
            any_param=(1, int, 'A parameter with a default'),
            needed=pkconfig.Required(int, 'A parameter with a default'),
        )

    Args:
        converter (callable): how to string to internal value
        docstring (str): description of parameter
    """
    @staticmethod
    def __new__(cls, *args):
        assert len(args) == 2, \
            '{}: incorrect number of args'.format(args)
        return super(Required, cls).__new__(cls, (None,) + args)


def append_load_path(load_path):
    """Called by entry point modules to add packages into the load path

    Args:
        load_path (str or list): separate by ``:`` or list of packages to append
    """
    global _load_path
    prev = _load_path
    for p in _load_path_parser(load_path):
        if not p in _load_path:
            _load_path.append(p)
    if prev != _load_path:
        global _raw_values
        assert not _raw_values, \
            'Values coalesced before load_path is initialized'

def channel_in(*args):
    """Test against configured channel

    Args:
        args (str): list of channels to valid

    Returns:
        bool: True if current channel in ``args``
    """
    res = False
    for a in args:
        assert a in VALID_CHANNELS, \
            '{}: invalid channel argument'.format(a)
        if a == cfg.channel:
            res = True
    return res


def channel_in_internal_test():
    """Is this a internal test channel?

    Returns:
        bool: True if current channel in (alpha, dev)
    """
    return channel_in(*INTERNAL_TEST_CHANNELS)


def init(**kwargs):
    """Declares and initializes config params for calling module.

    Args:
        kwargs (dict): param name to (default, parser, docstring)

    Returns:
        Params: `pkcollections.OrderedMapping` populated with param values
    """
    if '_caller_module' in kwargs:
        # Internal use only: _values() calls init() to initialize pkconfig.cfg
        m = kwargs['_caller_module']
        del kwargs['_caller_module']
    else:
        if pkinspect.is_caller_main():
            print(
                'pkconfig.init() called from __main__; cannot configure, ignoring',
                file=sys.stderr)
            return None
        m = pkinspect.caller_module()
    assert pkinspect.root_package(m) in _load_path, \
        '{}: module root not in load_path ({})'.format(m.__name__, _load_path)
    mnp = m.__name__.split('.')
    for k in reversed(mnp):
        kwargs = {k: kwargs}
    decls = {}
    _flatten_keys([], kwargs, decls)
    _coalesce_values()
    res = pkcollections.OrderedMapping()
    _iter_decls(decls, res)
    for k in mnp:
        res = res[k]
    return res


def parse_none(func):
    """Decorator for a parser which can parse None

    Args:
        callable: function to be decorated

    Returns:
        callable: func with attr indicating it can parse None
    """
    setattr(func, _PARSE_NONE_ATTR, True)
    return func


def reset_state_for_testing():
    """Clear the raw values so we can change load paths dynamically

    Only used for unit tests.
    """
    global _raw_values
    _raw_values = None


class _Declaration(object):
    """Initialize a single parameter declaration

    Args:
        name (str): for error output
        value (tuple or dict): specification for parameter

    Attributes:
        default (object): value to be assigned if not explicitly configured
        docstring (str): documentation for the parameter
        group (Group): None or Group instance
        parser (callable): how to parse a configured value
        required (bool): the param must be explicitly configured
    """
    def __init__(self, value):
        if isinstance(value, dict):
            self.group = value
            self.parser = None
            self.default = None
            self.docstring = ''
            #TODO(robnagler) _group_has_required(value)
            self.required = False
        else:
            assert len(value) == 3, \
                '{}: declaration must be a 3-tuple ({}.{})'.format(value, name)
            self.default = value[0]
            self.parser = value[1]
            self.docstring = value[2]
            assert callable(self.parser), \
                '{}: parser must be a callable ({}.{})'.format(self.parser, name)
            self.group = None
            self.required = isinstance(value, Required)


class _Key(str, object):
    """Internal representation of a key for a value

    The str value is uppercase joined with ``_``. For debugging,
    ``msg`` is printed (original case, joined on '.'). The parts
    are saved for creating nested values.
    """
    @staticmethod
    def __new__(cls, parts):
        self = super(_Key, cls).__new__(cls, '_'.join(parts).upper())
        self.parts = parts
        self.msg = '.'.join(parts)
        return self


def _clean_environ():
    """Ensure os.environ keys are valid (no bash function names)

    Also sets empty string to `None`.
    Returns:
        dict: copy of a cleaned up `os.environ`
    """
    res = {}
    for k in os.environ:
        if KEY_RE.search(k):
            res[k] = os.environ[k] if len(os.environ[k]) > 0 else None
    return res


def _coalesce_values():
    """Coalesce config files loaded from `cfg.load_path`

    Sets up load_path and channel then reads in base modules
    and home files. Finally imports os.environ.

    Returns:
        dict: nested values, top level is packages in load_path
    """
    global _raw_values
    global cfg
    if _raw_values:
        return _raw_values
    #TODO(robnagler) sufficient to set package and rely on HOME_FILE?
    append_load_path(os.getenv(LOAD_PATH_ENV_NAME, LOAD_PATH_DEFAULT))
    # Use current channel as the default in case called twice
    #TODO(robnagler) channel comes from file or environ
    #TODO(robnagler) import all modules then evaluate values
    #  code may initialize channel or load path
    #TODO(robnagler) append_load_path needs to be allowed in modules so
    #  reread path after each file/module load
    #TODO(robnagler) cache _values(), because need to be consistent
    channel = os.getenv(CHANNEL_ENV_NAME, CHANNEL_DEFAULT)
    assert channel in VALID_CHANNELS, \
        '{}: invalid ${}; must be {}'.format(
            channel, CHANNEL_ENV_NAME, VALID_CHANNELS)
    values = {}
    for p in _load_path:
        try:
            # base_pkconfig used to be required, import if available
            m = importlib.import_module(BASE_MODULE.format(p))
            _values_flatten(values, getattr(m, channel)())
        except ImportError:
            pass
    for p in _load_path:
        fname = os.path.expanduser(HOME_FILE.format(p))
        # The module itself may throw an exception so can't use try, because
        # interpretation of the exception doesn't make sense. It would be
        # better if run_path() returned a special exception when the file
        # does not exist.
        if os.path.isfile(fname):
            m = pkrunpy.run_path_as_module(fname)
            _values_flatten(values, getattr(m, channel)())
    env = _clean_environ()
    _values_flatten(values, env)
    values[CHANNEL_ENV_NAME] = channel
    values[LOAD_PATH_ENV_NAME] = list(_load_path)
    _raw_values = values
    _init_parsed_values(env)
    cfg = init(
        _caller_module=sys.modules[__name__],
        load_path=Required(list, 'list of packages to configure'),
        channel=Required(str, 'which (stage) function returns config'),
    )
    return _raw_values


def _flatten_keys(key_parts, values, res):
    """Turns values into non-nested dict with `_Key` keys, flat

    Args:
        key_parts (list): call with ``[]``
        values (dict): nested dicts of config values
        res (dict): result container (call with ``{}``)
    """
    for k in values:
        v = values[k]
        k = _Key(key_parts + k.split('.'))
        assert KEY_RE.search(k), \
            '{}: invalid key must match {}'.format(k.msg, KEY_RE)
        assert not k in res, \
            '{}: duplicate key'.format(k.msg)
        if isinstance(v, dict):
            _flatten_keys(k.parts, v, res)
        else:
            # Only store leaves
            res[k] = v


def _init_parsed_values(env):
    """Removes any values that match load_path from env

    Args:
        env (dict): cleaned os.environ
    """
    global _parsed_values
    _parsed_values = {}
    r = re.compile('^(' + '|'.join(_load_path) + ')_$', flags=re.IGNORECASE)
    for k in env:
        if not r.search(k):
            _parsed_values[_Key([k])] = env[k]


def _iter_decls(decls, res):
    """Iterates decls and resolves values into res

    Args:
        decls (dict): nested dictionary of a module's cfg values
        res (OrderedMapping): result configuration for module
    """
    for k in sorted(decls.keys()):
        #TODO(robnagler) deal with keys with '.' in them (not possible?)
        d = _Declaration(decls[k])
        r = res
        for kp in k.parts[:-1]:
            if kp not in r:
                r[kp] = pkcollections.OrderedMapping()
            r = r[kp]
        kp = k.parts[-1]
        if d.group:
            r[kp] = pkcollections.OrderedMapping()
            continue
        r[kp] = _resolver(d)(k, d)
        _parsed_values[k] = r[kp]


def _resolver(decl):
    """How to resolve values for declaration

    Args:
        decl (_Declaration): what to resolve

    Returns:
        callable: `_resolve_dict`, `_resolve_list`, or `_resolve_value`
    """
    if dict == decl.parser:
        return _resolve_dict
    if list == decl.parser:
        return _resolve_list
    return _resolve_value


def _resolve_dict(key, decl):
    #TODO(robnagler) assert "required"
    res = pkcollections.OrderedMapping(
        copy.deepcopy(decl.default) if decl.default else {})
    assert isinstance(res, (dict, pkcollections.OrderedMapping)), \
        '{}: default ({}) must be a dict'.format(key.msg, decl.default)
    key_prefix = key + '_'
    for k in reversed(sorted(_raw_values.keys())):
        if k != key and not k.startswith(key_prefix):
            continue
        r = res
        if len(k.parts) == 1:
            # os.environ has only one part (no way to split on '.')
            # so we have to assign the key's suffix manually
            ki = k.parts[0][len(key_prefix):]
            #TODO(robnagler) if key exists, preserve case (only for environ)
        else:
            kp = k.parts[len(key.parts):-1]
            for k2 in kp:
                if not k2 in r:
                    r[k2] = pkcollections.OrderedMapping()
                else:
                    assert isinstance(r[k2], (dict, pkcollections.OrderedMapping)), \
                        '{}: type collision on existing non-dict ({}={})'.format(
                            k.msg, k2, r[k2])
                r = r[k2]
            ki = k.parts[-1]
        r[ki] = _raw_values[k]
    return res


def _resolve_list(key, decl):
    #TODO(robnagler) assert required
    res = copy.deepcopy(decl.default) if decl.default else []
    assert isinstance(res, list), \
        '{}: default ({}) must be a list'.format(key.msg, decl.default)
    if key not in _raw_values:
        assert not decl.required, \
            '{}: config value missing and is required'.format(k)
        return res
    if not isinstance(_raw_values[key], list):
        if _raw_values[key] is None:
            return None
        raise AssertionError(
            '{}: value ({}) must be a list or None'.format(key.msg, _raw_values[key]))
    return _raw_values[key] + res


def _resolve_value(key, decl):
    if key in _raw_values:
        res = _raw_values[key]
    else:
        assert not decl.required, \
            '{}: config value missing and is required'.format(key.msg)
        res = decl.default
    seen = {}
    while isinstance(res, _string_types) \
        and not isinstance(res, Verbatim) \
        and not res in seen:
        seen[res] = 1
        res = res.format(**_parsed_values)
    #TODO(robnagler) FOO_BAR='' will not be evaluated. It may need to be
    # if None is not a valid option and there is a default
    if res is None and not hasattr(decl.parser, _PARSE_NONE_ATTR):
        return None
    return decl.parser(res)


def _load_path_parser(value):
    """Parses load path into list

    Args:
        value (object): str separated by colons or iterable

    Returns:
        list: Path containing packages.
    """
    if not value:
        return []
    if isinstance(value, _string_types):
        return value.split(LOAD_PATH_SEP)
    return value[:]


def _values_flatten(base, new):
    new_values = {}
    _flatten_keys([], new, new_values)
    #TODO(robnagler) Verify that a value x_y_z isn't set when x_y
    # exists already as a None. The other way is ok, because it
    # clears the value unless of course it's not a dict
    # then it would be a type collision
    for k in sorted(new_values.keys()):
        n = new_values[k]
        if k in base:
            b = base[k]
            if isinstance(b, list) or isinstance(n, list):
                if b is None or n is None:
                    pass
                elif isinstance(b, list) and isinstance(n, list):
                    n = n + b
                else:
                    raise AssertionError(
                        '{}: type mismatch between new value ({}) and base ({})'.format(
                            k.msg, n, b))
        base[k] = n
