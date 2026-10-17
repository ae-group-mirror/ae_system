"""
Python system helpers
=====================

the ae.system portion provides base helpers for the Python and OS systems environments.

.. note::
    on import, this module checks if it is running on the Android OS. if so, it will monkey patch the
    :mod:`shutil` module to ensure functions like ``copy`` and ``move`` work correctly. to prevent
    permission-related errors, this module should be one of the first imports in your Android app's main module.


operating system info helpers
-----------------------------

useful helper functions to inspect the operating system:

* :data:`os_platform`: a string identifying the operating system (e.g., 'linux', 'win32', 'android', 'ios').
* :data:`os_device_id`: a string with the ID/name of the device.
* :func:`os_host_name`: determines the operating system's host/machine name.
* :func:`os_local_ip`: determines the local IP address of the machine.
* :func:`os_user_name`: determines the current logged-in user's name.


manage OS environment variables & ``.env`` files
------------------------------------------------

* :func:`parse_dotenv`: parses a ``.env`` file and returns its key-value pairs as a dictionary.
* :func:`late_env_var_resolver`: substitutes environment variables within the value of other environment variables.
* :func:`load_dotenvs`: detects and loads all relevant ``.env`` files from the current working directory and optional
  also from the main module's path.
* :func:`load_env_var_defaults`: recursively searches parent directories for ``.env`` files and loads any undeclared
  variables.
* :func:`sys_env_dict`: returns a dictionary containing the most important Python runtime OS environment values.
* :func:`sys_env_text`: compiles a formatted text block with system environment information, useful for logging.


Python virtual environment helpers
----------------------------------

Python virtual environment core helpers working for standard virtual environments (venv, virtualenv, inclusive
local .venv-folders), for pyenv, Miniconda, Conda and for tools like Poetry, Pipenv and uv.

* :func:`os_env_venv`: determines the id/name of the currently Python virtual environment (VENV) set in the OS env vars.
* :func:`venv_prefix`: determine the folder path of the prefix/root name of the currently set VENV in the OS env vars.

.. hint:: more helpers related to Python virtual environments are provided by the module :mod:`aedev.commands`.


application & project helpers
-----------------------------

functions to aid in application setup, configuration, and build introspection.

* :func:`app_name_guess`: attempts to determine the name of the currently running application from its environment.
* :func:`build_config_variable_values`: reads variable values from a 'buildozer.spec' file.
* :func:`instantiate_config_parser`: returns a `ConfigParser` instance pre-configured for case-sensitive keys and
  extended interpolation.


modules and call stack inspection
---------------------------------

dynamically inspect modules, execution frames, and variables on the call stack.

* :func:`module_attr`: dynamically gets a reference to a module or any attribute (variable, function, class) within it.
* :func:`module_file_path`: determines the absolute file path of the module from which it is called.
* :func:`module_find`: determine the file path of a Python module.
* :func:`module_load`: search, import and execute a Python module dynamically without adding it to sys.modules.
* :func:`stack_frames`: a generator that yields frames from the call stack, starting at a specified depth.
* :func:`stack_var`: finds the value of a specific variable by searching up the call stack.
* :func:`stack_vars`: returns the global and local variables from a specific frame in the call stack.
* :func:`full_stack_trace`: generates a complete, detailed stack trace including local variables from an exception.

.. hint::
    the :class:`ae.core.AppBase` class uses these helper functions to determine the
    :attr:`version <ae.core.AppBase.app_version>` and :attr:`title <ae.core.AppBase.app_title>` of an application,
    if these values are not specified in the instance initializer.


system constants and classes
----------------------------

* :data:`DOTENV_LINE_MATCHER`: compiled regular expression to parse a line of an OS environment file.
* :data:`DOTENV_VAR_IN_VAL_MATCHER`: compiled regular expression to parse the value of an OS env variable.
* :data:`SKIPPED_MODULES`: a tuple of module names to be ignored by stack inspection functions.

"""
import getpass
import importlib
import importlib.abc
import importlib.util
import inspect
import os
import platform
import re
import shutil
import socket
import sys
import warnings

from collections.abc import Callable, Container, Generator, MutableMapping
from configparser import ConfigParser, ExtendedInterpolation
from importlib.machinery import ModuleSpec
from inspect import getinnerframes, getouterframes, getsourcefile
from types import ModuleType
from typing import Any, cast

from ae.base import (                                               # type: ignore
    UNSET,
    defuse, dummy_function, env_str, mask_secrets, norm_path,
    os_path_abspath, os_path_basename, os_path_dirname, os_path_isfile, os_path_join, os_path_splitext,
    pep8_format, read_file,
    UnsetType)


__version__ = '0.3.21'


DOTENV_LINE_MATCHER = re.compile(r"""
    ^
    (?:export\s+)?              # optional export
    ([\w.]+)                    # env variable name
    (?:\s*=\s*|:\s+?)           # separator
    (                           # optional value begin
        '(?:\'|[^'])*'          #   single quoted value
        |                       #   or
        "(?:\"|[^"])*"          #   double quoted value
        |                       #   or
        (?:[^\n#]|(?<!\s)\#)+   #   unquoted value (#-char included in variable value, if not prefixed with whitespace)
    )?                          # value end
    (?:\s*\#.*)?                # optional comment
    $
    """, re.VERBOSE)
""" .env file line parsing regex. """

DOTENV_VAR_IN_VAL_MATCHER = re.compile(r"""
    (\\)?                       # escaped with a backslash? (env variable name matcher groups item 0 | evn_groups[0])
    (\$)                        # literal $ (matcher evn_groups[1])
    (                           # group for easier subsitution via evn_groups[0:-1] (matcher evn_groups[2])
        \{?                     #   allow brace wrapping
        ([A-Za-z0-9_:\-]+)      #   match var name including default value (matcher evn_groups[3|-1]
        }?                      #   closing brace
    )                           # braces end
    """, re.IGNORECASE | re.VERBOSE)
""" .env variable name expansion in variable value; allowing lowercase var names and shell var default value ops (see
<https://www.gnu.org/software/bash/manual/bash.html#Shell-Parameter-Expansion-1>) """

SKIPPED_MODULES = (
    'ae.base', 'ae.app_log', 'ae.dynamicod', 'ae.system', 'ae.deep', 'ae.django_utils', 'ae.notify', 'ae.valid',
    'ae.files', 'ae.paths', 'ae.i18n', 'ae.cloud_storage', 'ae.oaio_model', 'ae.oaio_client', 'ae.updater',
    'ae.core', 'ae.literal', 'ae.config', 'ae.console', 'ae.shell', 'ae.managed_files', 'ae.pythonanywhere',
    'ae.lockname', 'ae.progress', 'ae.sys_core', 'ae.sys_data', 'ae.sys_core_sh', 'ae.sys_data_sh',
    'ae.db_core', 'ae.db_ora', 'ae.db_pg', 'ae.transfer_service', 'ae.sideloading_server',
    'ae.gui', 'ae.gui.app', 'ae.gui.tours', 'ae.gui.utils',
    'ae.kivy_glsl', 'ae.kivy_dyn_chi', 'ae.kivy_relief_canvas',
    'ae.kivy', 'ae.kivy.apps', 'ae.kivy.behaviors', 'ae.kivy.i18n', 'ae.kivy.tours', 'ae.kivy.widgets',
    'ae.kivy_auto_width', 'ae.kivy_file_chooser', 'ae.kivy_iterable_displayer', 'ae.kivy_qr_displayer',
    'ae.kivy_sideloading', 'ae.kivy_user_prefs', 'ae.lisz_app_data',
    'ae.enaml_app', 'ae.toga_app', 'ae.pyglet_app', 'ae.pygobject_app', 'ae.dabo_app', 'ae.qpython_app',
    'importlib._bootstrap', 'importlib._bootstrap_external')
""" skipped modules used as default by :func:`stack_var` and :func:`stack_vars` """


EnvVarsType = MutableMapping[str, str]               #: environment variables dict/mapping
EnvVarsLateResolvedType = dict[str, list[tuple[str, str, str, str]]]     #: mapping of DOTENV_VAR_IN_VAL_MATCHER results


def app_name_guess() -> str:
    """ guess/try to determine the name of the currently running app (w/o assessing not yet initialized app instance).

    :return:                    application name/id or 'unguessable' if not guessable.
    """
    app_name = build_config_variable_values(('package.name', ""))[0]
    if not app_name:
        unspecified_names = ('ae_base', 'ae_system', 'app',
                             '_jb_pytest_runner', 'main', '__main__', 'pydevconsole', 'pytest', 'src')
        path = sys.argv[0]
        app_name = os_path_splitext(os_path_basename(path))[0]
        if app_name.lower() in unspecified_names:
            path = os.getcwd()
            app_name = os_path_basename(path)
            if app_name.lower() in unspecified_names:
                app_name = "unguessable"
    return defuse(app_name)


def build_config_variable_values(*names_defaults: tuple[str, Any], section: str = 'app') -> tuple[Any, ...]:
    """ determine build config variable values from the ``buildozer.spec`` file in the current directory.

    :param names_defaults:      tuple of tuples of build config variable names and default values.
    :param section:             name of the spec file section, using 'app' as default.
    :return:                    tuple of build config variable values (using the passed default value if not specified
                                in the 'buildozer.spec' file or if this file does not exist in cwd).
    """
    if not os_path_isfile('buildozer.spec'):
        return tuple(def_val for name, def_val in names_defaults)

    config = instantiate_config_parser()
    config.read('buildozer.spec', 'utf-8')

    return tuple(config.get(section, name, fallback=def_val) for name, def_val in names_defaults)


def full_stack_trace(ex: Exception, frames_with_locals: int = 3) -> str:
    """ generates a complete, detailed stack trace including local variables from an exception.

    :param ex:                  exception instance.
    :param frames_with_locals:  number of the deepest frames to show also the local variables for.
    :return:                    text block string (formatted by os.linesep) with stack trace info.
    """
    ret = f"Exception {ex!r}. Full traceback (last {frames_with_locals} frames with locals):" + os.linesep
    trace_back = sys.exc_info()[2]
    if trace_back:
        def ext_ret(frame_info: inspect.FrameInfo):
            """ process traceback frame and add as str to ret """
            nonlocal ret
            ret += f'File "{frame_info[1]}", line {frame_info[2]}, in {frame_info[3]}' + os.linesep
            lines = frame_info[4]  # mypy does not detect item[]
            if lines:
                for line in lines:
                    ret += ' ' * 4 + line.lstrip()

        all_frames = list(reversed(getouterframes(trace_back.tb_frame)[1:])) + getinnerframes(trace_back)
        first_locals_idx = len(all_frames) - frames_with_locals
        for idx, info in enumerate(all_frames):
            ext_ret(info)
            if idx >= first_locals_idx:
                for nam, val in info.frame.f_locals.items():
                    val = pep8_format(val, indent_level=2, debug_mode=True)
                    # noinspection PyStringConversionWithoutDunderMethod
                    ret += ' ' * 6 + f"= {nam}: {type(val)} = {val}" + os.linesep

    return ret


def instantiate_config_parser() -> ConfigParser:
    """ instantiate and prepare config file parser.

    ensures that the :class:`~configparser.ConfigParser` instance is correctly configured, e.g., to support
    case-sensitive config variable names and to use :class:`ExtendedInterpolation` as the interpolation argument.
    """
    cfg_parser = ConfigParser(allow_no_value=True, interpolation=ExtendedInterpolation())
    setattr(cfg_parser, 'optionxform', str)     # for case-sensitive var names (or use 'lambda option: option')
    return cfg_parser


def late_env_var_resolver(env_vars: EnvVarsType, loaded_vars: EnvVarsType, late_resolved: EnvVarsLateResolvedType):
    """ late resolve/expand/substitute of env variables in env var values.

    :param env_vars:            cached environment variables (prioritized over os.environ), which will get substituted.
                                also used to search&resolve env var values (if not exist, then searched in os.environ).
    :param loaded_vars:         recently loaded environment variables, will get substituted.
    :param late_resolved:       matches of loaded env vars to be resolved late (after all env vars got detected and
                                loaded). each key of this dict is the name of the env variable which has other env vars
                                in its values to be resolved/substituted. each item value of this dict is a list of
                                matcher group tuples for each found env variable. the group/tuple items are
                                (0) escape character, (1) the dollar character, (2) the env var name literal (optionally
                                in curly brackets) and (3/-1) the env var name.
    """
    def _update_matches_retries() -> int:
        if evn_groups[0] == '\\':                                   # if escaped '$' character
            replace: str | None = "".join(evn_groups[1:-1])         # then only unescape (no var search&substitute)
        elif (replace := env_vars.get(evn_groups[-1])) is None:
            replace = os.environ.get(evn_groups[-1])
        if replace is not None:
            var_val = loaded_vars[var_nam]
            env_vars[var_nam] = loaded_vars[var_nam] = var_val.replace("".join(evn_groups[0:-1]), replace)
            matches.remove(evn_groups)
            if replacement_matches := DOTENV_VAR_IN_VAL_MATCHER.findall(replace):
                if any(_[-1] == var_nam for _ in replacement_matches):
                    warnings.warn(f"   ## ignoring recursive environment variable {var_nam} ({var_val=})")
                    replacement_matches = [_ for _ in replacement_matches if _[-1] != var_nam]
                matches.extend(replacement_matches)     # extend matches with env vars in replaced var value
                return len(replacement_matches)
        return 0

    retries = len(late_resolved)                        # retry if later-/not-yet-replaced env var in env var value
    while late_resolved and retries:
        for var_nam, matches in late_resolved.copy().items():
            # substitute declared and not escaped env variables found via :data:`DOTENV_VAR_IN_VAL_MATCHER` in a value
            for evn_groups in matches.copy():           # try to replace env vars with its values, removed from matches
                retries += _update_matches_retries()
            if not matches:
                late_resolved.pop(var_nam)
        retries -= 1

    for var_nam, matches in late_resolved.items():
        warnings.warn(f"   ## {var_nam=} has unresolved environment variables in its value: {[_[-1] for _ in matches]}"
                      f"; env_vars['{var_nam}']={env_vars.get(var_nam, 'not in dict')}"
                      f" loaded_vars['{var_nam}']={loaded_vars.get(var_nam, 'not in dict')}")


def load_dotenvs(from_module_path: bool = False):
    """ detect and load not defined OS environment variables from ``.env`` files.

    :param from_module_path:    pass True to load OS environment variables (that are not already loaded from ``.env``
                                files situated in or above the current working directory) also from/above the folder of
                                the first module in the call stack that gets not excluded/skipped by :func:`stack_var`.

                                in order to also load ``.env`` files in/above the project folder.
                                call this function from the main module of project/app.

    .. note::
        only variables that are not already defined in the OS environment variables mapping :attr:`os.environ` will be
        loaded/added. variables will be loaded first from the first ``.env`` file found in or above the current working
        directory, while the variable values in the deeper situated files are overwriting the values defined in the
        ``.env`` files situated in the above folders.
    """
    env_vars = os.environ
    load_env_var_defaults(os.getcwd(), env_vars)

    if from_module_path and (file_name := stack_var('__file__')):
        load_env_var_defaults(os_path_dirname(os_path_abspath(cast(str, file_name))), env_vars)


def load_env_var_defaults(start_dir: str, env_vars: EnvVarsType) -> EnvVarsType:
    """ load undeclared env var defaults from a chain of ``.env`` files starting in the specified folder or its parent.

    :param start_dir:           folder to start search of an ``.env`` file, if not found, then also checks the parent
                                folder. if an ``.env `` file got found, then put their shell environment variable values
                                into the  specified :paramref:`.env_vars` mapping if they are not
                                already there. after processing the first ``.env`` file, it repeats to check for
                                further ``.env`` files in the parent folder to load them too, until either detecting
                                a folder without an ``.env`` file or until an ``.env`` got loaded from the root folder.
    :param env_vars:            environment variables mapping to be amended with env variable values from any
                                found ``.env`` file. pass Python's :attr:`os.environ` to amend this mapping directly
                                with all the already not declared environment variables.
    :return:                    env var names (keys) and values added to :paramref:`.env_vars`.
    """
    start_dir = norm_path(start_dir)
    file_path = os_path_join(start_dir, '.env')
    if not os_path_isfile(file_path):
        file_path = os_path_join(os_path_dirname(start_dir), '.env')

    loaded_vars = {}
    late_resolved: EnvVarsLateResolvedType = {}
    last_path = ""                  # prevent endless-loop for '.env' in root dir
    while os_path_isfile(file_path) and last_path != file_path:
        for var_nam, var_val in parse_dotenv(file_path, late_resolved, exclude_vars=env_vars).items():
            env_vars[var_nam] = loaded_vars[var_nam] = var_val

        last_path = file_path
        file_path = os_path_join(os_path_dirname(os_path_dirname(file_path)), '.env')

    late_env_var_resolver(env_vars, loaded_vars, late_resolved)

    return loaded_vars


def module_attr(import_name: str, attr_name: str) -> Any | UnsetType | None:
    """ determine dynamically a reference to any attribute (variable/func/class) declared in a module.

    :param import_name:         import-/dot-name of the distribution/module/package to load/import.
    :param attr_name:           name of the attribute declared within the module.
    :return:                    module attribute value,
                                or None if the module got not found
                                or UNSET if the module attribute doesn't exist.

    .. note:: a previously not imported module will *not* be added to `sys.modules` by this function.

    """
    mod_ref = sys.modules.get(import_name, None) or module_load(import_name)
    return getattr(mod_ref, attr_name, UNSET) if isinstance(mod_ref, ModuleType) else None


def module_file_path(local_object: Callable | None = None) -> str:
    """ determine the absolute path of the module from which this function got called.

    :param local_object:        optional local module, class, method, function, traceback, frame, or code object of the
                                calling module (passing `lambda: 0` also works). omit this argument in order to use
                                the `__file__` module variable (which will not work if the module is frozen by
                                ``py2exe`` or ``PyInstaller``).
    :return:                    module path (inclusive module file name) or empty string if not found/determinable.
    """
    if local_object:
        file_path = getsourcefile(local_object)
        if file_path:
            return norm_path(file_path)

    file_path = stack_var('__file__')
    if not file_path:
        try:
            # noinspection PyProtectedMember
            file_path = sys._getframe().f_back.f_code.co_filename   # type: ignore # pylint: disable=protected-access
        except (AttributeError, Exception):                         # pylint: disable=broad-except
            file_path = ""
    return file_path


def module_find(import_name: str) -> str | list[str]:
    """ determine the file path of a Python module.

    :param import_name:         dot-name of the module to find.
    :return:                    absolute file path of the found module, else a list of error strings.
    """
    errors: list[str] = []
    path = ""
    try:
        spec = importlib.util.find_spec(import_name)
        if spec is None:
            errors.append(f"find_spec({import_name=}) did not find any module spec")
        elif spec.origin in (None, "", "built-in", "frozen"):
            if spec.loader_state and spec.loader_state.filename:
                path = spec.loader_state.filename
            elif spec.submodule_search_locations:
                path = spec.submodule_search_locations[0]   # take 1st dir of Namespace package with multiple locations
            else:
                errors.append(f"path not available for {spec.origin + '-' if spec.origin else ''}module {import_name}")
        else:
            path = spec.origin
    except (ValueError, Exception) as exc:  # pylint: disable=broad-exception-caught
        errors.append(f"find_spec({import_name=}) raised {exc=}")

    return errors or path


def module_load(import_name: str, path: str | UnsetType | None = UNSET) -> ModuleType | list[str]:
    """ search, import and execute a Python module dynamically without adding it to sys.modules.

    :param import_name:         dot-name of the module to import.
    :param path:                optional file path of the module to import. if this arg is not specified or has the
                                default value (:data:`UNSET`), then the path will be determined from the current working
                                directory and the import name. specify ``None`` to prevent the module search.
    :return:                    a reference to the module if the module could be loaded, else a list of error strings.
    """
    errors: list[str] = []

    if path is UNSET:
        path_parts = cast(str, os_path_join(*import_name.split('.')))
        if (os_path_isfile(path := path_parts + '.py') or
                os_path_isfile(path := os_path_join(path_parts, '__init__' + '.py'))):
            path = norm_path(path)
        else:
            path = _path_or_err if isinstance(_path_or_err := module_find(import_name), str) else None

    mod_ref: ModuleType | list[str] = [f"unexpected error in load of module {import_name}"]
    spec = importlib.util.spec_from_file_location(import_name, path, submodule_search_locations=[])
    if isinstance(spec, ModuleSpec):
        try:
            mod_ref = importlib.util.module_from_spec(spec)
            if isinstance(spec.loader, importlib.abc.Loader) and isinstance(mod_ref, ModuleType):
                spec.loader.exec_module(mod_ref)
            else:
                errors.append(f"spec.loader ({type(spec.loader)=} is not of importlib.abs.loader")
        except (FileNotFoundError, Exception) as exc:   # pylint: disable=broad-exception-caught
            errors.append(f"module_from_spec/exec_module({spec=}) raised {exc=}")
    else:
        errors.append(f"spec_from_file_location({import_name=}) could not load module at {path=}")

    return errors or mod_ref


def norm_pip_name(pip_name: str) -> str:
    """ normalize the project name of a package hosted at pypi.org.

    :param pip_name:            project name of a package, like shown in the pypi.org/project/<project_name> URL.
    :return:                    normalized project name, in lower case and all dots&underscores replaced by hyphens.
    """
    return pip_name.replace('.', '-').replace('_', '-').lower()


def os_env_venv() -> str:
    """ determine the id of the Python virtual environment (VENV) that is currently set in the OS environment variables.

    :return:                    the name/id of the currently set VENV in the OS env vars (:attr:`os.environ`)
                                or an empty string if no VENV is set in the OS environment variables.

                                .. note::
                                    this function is only checking the OS env vars and is not using :attr:`sys.prefix`
                                    or the expression ``sys.prefix == sys.base_prefix`` to determine if a VENV got set.

                                .. hint::
                                    if the Conda `base` VENV got set in the OS env vars, then the basename of the env
                                    var 'CONDA_PREFIX' ('anaconda3' or 'miniconda3') will be returned as VENV id. the
                                    env var `CONDA_DEFAULT_ENV` has in this case set the value 'base', and the path in
                                    :data:`sys.prefix` could be different to the value of 'CONDA_PREFIX' if the
                                    `base` VENV got only set within the OS environment variables.
    """
    path = venv_prefix()
    return os_path_basename(path) if path else ""


def os_host_name() -> str:
    """ determine the operating system host/machine name.

    :return:                    machine name string.
    """
    return defuse(platform.node()) or 'indeterminableHostName'


def os_local_ip() -> str:
    """ determine ip address of this system/machine in the local network (LAN or WLAN).

    inspired by answers of SO users @dml and @fatal_error to the question: https://stackoverflow.com/questions/166506.

    :return:                    ip address of this machine in the local network (WLAN or LAN/ethernet)
                                or empty string if this machine is not connected to any network.
    """
    socket1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ip_address = ""
    try:
        socket1.connect(('10.255.255.255', 1))                      # doesn't even have to be reachable
        ip_address = socket1.getsockname()[0]
    except (OSError, IOError, Exception):                           # pylint: disable=broad-except
        # ConnectionAbortedError, ConnectionError, ConnectionRefusedError, ConnectionResetError inherit from OSError
        socket2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            socket2.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            socket2.connect(('<broadcast>', 0))
            ip_address = socket2.getsockname()[0]
        except (OSError, IOError, Exception):                       # pylint: disable=broad-except
            pass
        finally:
            socket2.close()
    finally:
        socket1.close()

    return ip_address


def _os_platform() -> str:
    """ determine the operating system where this code is running (used to initialize the :data:`os_platform` variable).

    :return:                    operating system (extension) as string. extending Python's :func:`sys.platform`
                                for mobile platforms like Android and iOS:

                                * `'android'` for all Android systems.
                                * `'cygwin'` for MS Windows with an installed Cygwin extension.
                                * `'darwin'` for all Apple Mac OS X systems.
                                * `'freebsd'` for all other BSD-based unix systems.
                                * `'ios'` for all Apple iOS systems.
                                * `'linux'` for all other unix systems (like e.g. Arch, Debian/Ubuntu, Suse).
                                * `'win32'` for MS Windows systems (w/o the Cygwin extension).

    """
    if env_str('ANDROID_ARGUMENT') is not None:     # p4a env variable; alternatively use ANDROID_PRIVATE
        return 'android'
    return env_str('KIVY_BUILD') or sys.platform    # KIVY_BUILD == 'android' / 'ios' on Android/iOS


os_platform = _os_platform()
""" operating system / platform string (see :func:`_os_platform`).

this string value gets determined for most of the operating systems with the help of Python's :func:`sys.platform`
function and additionally detects the operating systems iOS and Android (currently not fully supported by Python).
"""


os_device_id = os_host_name()
""" user-definable id/name of the device, defaults to os_host_name() on most platforms, alternatives are:

on Android (check with adb shell 'settings get global device_name' and adb shell 'settings list global'):
    - Settings.Global.DEVICE_NAME (Settings.Global.getString(context.getContentResolver(), "device_name"))
    - android.os.Build.DEVICE/.MANUFACTURER/.BRAND/.HOST
    - DeviceName.getDeviceName()
on MS Windows:
    - os.environ['COMPUTERNAME']
on all other platforms:
    - socket.gethostname()
"""
if os_platform == 'android':
    # determine Android device id because os_host_name() returns mostly 'localhost' and not the user-definable device id
    from jnius import autoclass                                     # type: ignore

    # noinspection PyBroadException
    try:
        Settings = autoclass('android.provider.Settings$Global')
        PythonActivity = autoclass('org.kivy.android.PythonActivity')

        # mActivity inherits from Context so no need to cast('android.content.Context',..) neither get app context
        # _Context = autoclass('android.content.Context')
        # context = cast('android.content.Context', PythonActivity.mActivity)
        # context = PythonActivity.mActivity.getApplicationContext()
        context = PythonActivity.mActivity
        if _dev_id := Settings.getString(context.getContentResolver(), 'device_name'):
            os_device_id = defuse(_dev_id)

    except Exception:                                               # pylint: disable=broad-except
        pass

    # monkey patches the :func:`shutil.copystat` and :func:`shutil.copymode` helper functions, which are crashing on
    # 'android' (see # `<https://bugs.python.org/issue28141>`__ and `<https://bugs.python.org/issue32073>`__). these
    # functions are used by shutil.copy2/copy/copytree/move to copy OS-specific file attributes.
    # although shutil.copytree() and shutil.move() are copying/moving the files correctly when the copy_function
    # arg is set to :func:`shutil.copyfile`, they will finally also crash afterward when they try to set the attributes
    # on the destination root directory.
    shutil.copymode = dummy_function
    shutil.copystat = dummy_function


elif os_platform in ('win32', 'cygwin'):
    if _dev_id := os.environ.get('COMPUTERNAME'):
        os_device_id = defuse(_dev_id)


def os_user_name() -> str:
    """ determine the operating system username.

    :return:                    username string.
    """
    return getpass.getuser()


def parse_dotenv(file_path: str, late_resolved: EnvVarsLateResolvedType, exclude_vars: Container = ()) -> EnvVarsType:
    """ parse ``.env`` file content and return environment variable names as dict keys and values as dict values.

    :param file_path:           string with the name/path of an existing `'.env'` file.
    :param late_resolved:       mapping extended with matches of env vars found in the returned env var values.
    :param exclude_vars:        names of env vars to preserve their value (do not return).
    :return:                    mapping with parsed environment variable names and values.
    """
    lines = []          # unwrap multi-line .env variable values with backslash at line end (Docker/UNIX-style format)
    prev_lines = ""
    for line in read_file(file_path).splitlines():
        if line.endswith('\\'):
            prev_lines += line[:-1]
            continue
        lines.append(prev_lines + line)
        prev_lines = ""

    env_vars: EnvVarsType = {}
    for line in lines:
        match = DOTENV_LINE_MATCHER.search(line)
        if not match:
            if not re.search(r'^\s*(?:#.*)?$', line):  # not comment or blank
                warnings.warn(f"'{line!r}' in '{file_path}' doesn't match {'.env'} format", SyntaxWarning)
            continue

        var_nam, var_val = match.groups()
        if var_nam in exclude_vars:
            continue
        var_val = "" if var_val is None else var_val.strip()

        # remove surrounding quotes, unescape all chars except $ so variables can be escaped properly
        match = re.match(r'^([\'"])(.*)\1$', var_val)
        if match:
            delimiter, var_val = match.groups()
            if delimiter == '"':
                var_val = re.sub(r'\\([^$])', r'\1', var_val)
        else:
            delimiter = None
        if delimiter != "'":    # https://www.gnu.org/savannah-checkouts/gnu/bash/manual/bash.html#Single-Quotes
            if matches := DOTENV_VAR_IN_VAL_MATCHER.findall(var_val):
                late_resolved[var_nam] = matches

        env_vars[var_nam] = var_val

    return env_vars


def stack_frames(depth: int = 1) -> Generator:  # Generator[frame, None, None]
    """ generator returning the call stack frame from the level given in :paramref:`.depth`.

    :param depth:               the stack level to start; the first returned frame by this generator. the default value
                                (1) refers to the next deeper stack frame, respectively the one of the caller of this
                                function. pass 2 or a higher value if you want to start with an even deeper frame/level.
    :return:                    generated frames of the call stack.
    """
    try:
        while True:
            depth += 1
            # noinspection PyProtectedMember
            yield sys._getframe(depth)          # pylint: disable=protected-access
    except (TypeError, AttributeError, ValueError):
        pass


def stack_var(name: str, *skip_modules: str, scope: str = '', depth: int = 1) -> Any | None:
    """ determine variable value in calling stack/frames.

    :param name:                variable name to search in the calling stack frames.
    :param skip_modules:        module names to skip (def=see :data:`SKIPPED_MODULES` module constant).
    :param scope:               pass 'locals' to only check for local variables (ignoring globals) or
                                'globals' to only check for global variables (ignoring locals). the default value (an
                                empty string) will not restrict the scope, returning either a local or global value.
    :param depth:               the calling level from which on to search. the default value (1) refers to the next
                                deeper stack frame, which is the caller of the function. pass 2 or an even higher
                                value if you want to start the variable search from a deeper level in the call stack.
    :return:                    the variable value of a deeper level within the call stack or UNSET if the variable was
                                not found.
    """
    glo, loc, _deep = stack_vars(*skip_modules, find_name=name, min_depth=depth + 1, scope=scope)
    variables = glo if name in glo and scope != 'locals' else loc
    return variables.get(name, UNSET)


def stack_vars(*skip_modules: str,
               find_name: str = '', min_depth: int = 1, max_depth: int = 0, scope: str = ''
               ) -> tuple[dict[str, Any], dict[str, Any], int]:
    """ determine all global and local variables in a calling stack/frames.

    :param skip_modules:        module names to skip (def=see :data:`SKIPPED_MODULES` module constant).
    :param find_name:           if passed, then the returned stack frame must contain a variable with the passed name.
    :param scope:               scope to search the variable name passed via :paramref:`.find_name`. pass
                                'locals' to only search for local variables (ignoring globals) or 'globals' to only
                                check for global variables (ignoring locals). passing an empty string will find the
                                variable within either locals or globals.
    :param min_depth:           the call stack level from which on to search. the default value (1) refers the next
                                deeper stack frame, respectively, to the caller of this function. pass 2 or a higher
                                value if you want to get the variables from a deeper level in the call stack.
    :param max_depth:           the maximum depth in the call stack from which to return the variables. if the specified
                                argument is not zero and no :paramref:`.skip_modules` are specified, then the
                                first deeper stack frame that is not within the default :data:`SKIPPED_MODULES` will be
                                returned. if this argument and :paramref:`.find_name` get not passed,
                                then the variables of the top stack frame will be returned.
    :return:                    tuple of the global and local variable dicts and the depth in the call stack.
    """
    if not skip_modules:
        skip_modules = SKIPPED_MODULES
    glo = loc = {}
    depth = min_depth + 1   # +1 for stack_frames()
    for frame in stack_frames(depth=depth):
        depth += 1
        glo, loc = frame.f_globals, frame.f_locals

        if glo.get('__name__') in skip_modules:
            continue
        if find_name and (find_name in glo and scope != 'locals' or find_name in loc and scope != 'globals'):
            break
        if max_depth and depth > max_depth:
            break
    # experienced strange overwrites of locals (e.g., self) when returning f_locals directly (adding .copy() fixed it)
    # check if f_locals is a dict (because enaml is using their DynamicScope object, which is missing a copy method)
    if isinstance(loc, dict):
        loc = loc.copy()
    return glo.copy(), loc, depth - 1


def sys_env_dict() -> dict[str, Any]:
    """ returns dict with python system run-time environment values.

    :return:                    python system run-time environment values like python_ver, argv, cwd, executable,
                                frozen and bundle_dir (if bundled with pyinstaller).

    .. hint:: see also https://pyinstaller.readthedocs.io/en/stable/runtime-information.html
    """
    sed: dict[str, Any] = {
        'python ver': sys.version_info,
        'platform': os_platform,
        'argv': sys.argv,
        'executable': sys.executable,
        'cwd': os.getcwd(),
        'frozen': getattr(sys, 'frozen', False),
        'user name': os_user_name(),
        'host name': os_host_name(),
        'device id': os_device_id,
        'app_name_guess': app_name_guess(),
        'OS env': mask_secrets(os.environ.copy()),
    }

    if sed['frozen']:
        sed['bundle_dir'] = getattr(sys, '_MEIPASS', '*#ERR#*')

    return sed


def sys_env_text(ind_ch: str = " ", ind_len: int = 12, key_ch: str = "=", key_len: int = 15,
                 extra_sys_env_dict: EnvVarsType | None = None) -> str:
    """ compile a formatted text block with system environment info.

    :param ind_ch:              indent character (defaults to " ").
    :param ind_len:             indent depths (default=12 characters).
    :param key_ch:              key-value separator character (default="=").
    :param key_len:             key-name minimum length (default=15 characters).
    :param extra_sys_env_dict:  dict with additional system info items.
    :return:                    text block with system environment info.
    """
    sed = sys_env_dict()
    if extra_sys_env_dict:
        sed.update(extra_sys_env_dict)
    key_len = max([key_len] + [len(key) + 1 for key in sed])

    ind = ""
    text = os.linesep.join([f"{ind:{ind_ch}>{ind_len}}{key:{key_ch}<{key_len}}{val}" for key, val in sed.items()])

    return text


def venv_prefix() -> str:
    """ determine the path of the VENV prefix/root folder which is currently set in the OS environment vars.

    :return:                    normalized prefix/root folder path of the currently set VENV (Python virtual
                                environment) in the OS environment variables (:attr:`os.environ`),
                                or an empty string if no VENV is set in the OS env vars.
    """
    venv_path = os.getenv('VIRTUAL_ENV') or os.getenv('CONDA_PREFIX')
    return norm_path(venv_path) if venv_path else ""   # normalize found path, also for bash-emulation under win32
