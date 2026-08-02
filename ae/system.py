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


manage environment variables & `.env` files
-------------------------------------------

* :func:`parse_dotenv`: parses a `.env` file and returns its key-value pairs as a dictionary.
* :func:`late_env_var_resolver`: substitutes environment variables within the value of other environment variables.
* :func:`load_dotenvs`: detects and loads all relevant `.env` files from the current working directory and optional
  also from the main module's path.
* :func:`load_env_var_defaults`: recursively searches parent directories for `.env` files and loads any undeclared
  variables.
* :func:`sys_env_dict`: returns a dictionary containing the most important Python runtime OS environment values.
* :func:`sys_env_text`: compiles a formatted text block with system environment information, useful for logging.


application & project helpers
-----------------------------

functions to aid in application setup, configuration, and build introspection.

* :func:`app_name_guess`: attempts to determine the name of the currently running application from its environment.
* :func:`build_config_variable_values`: reads variable values from an APP_BUILD_CFG_FILENAME/`buildozer.spec` file.
* :func:`instantiate_config_parser`: returns a `ConfigParser` instance pre-configured for case-sensitive keys and
  extended interpolation.
* :func:`project_main_file`: determines the absolute path to the main module file of a project package (where the
  `__version__` of the app|package is defined).
* :func:`main_file_paths_parts`: returns a tuple of possible main/version file path names combinations of any project.


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

* :data:`APP_BUILD_CFG_FILENAME`: default name for a build configuration file (buildozer.spec).
* :data:`DOTENV_FILENAME`: default name for environment variable files (.env).
* :data:`DOTENV_LINE_MATCHER`: compiled regular expression to parse a line of an OS environment file.
* :data:`DOTENV_VAR_IN_VAL_MATCHER`: compiled regular expression to parse the value of an OS env variable.
* :data:`PYPI_PACKAGE_NAMES`: irregular project/package names, not convertable from their import names.
* :data:`SKIPPED_MODULES`: a tuple of module names to be ignored by stack inspection functions.

an instance of the class :class:`PyMo` is representing a Python module/package, and provides:

* project, namespace, module, package and portion names
* project, module, package and portion paths
* dynamic load of a code module or package
"""
# pylint: disable=too-many-lines
import getpass
import importlib
import importlib.abc
import importlib.util
import inspect
import itertools
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
from typing import Any, Self, cast

from ae.base import (                                               # type: ignore
    PY_EXT, PY_INIT, PY_MAIN, UNSET,
    defuse, dummy_function, env_str, mask_secrets, norm_path,
    os_path_abspath, os_path_basename, os_path_dirname, os_path_isfile, os_path_join, os_path_splitext,
    read_file, UnsetType)
from ae.app_log import ErrorMsgMixin                                # type: ignore


__version__ = '0.3.11'


APP_BUILD_CFG_FILENAME = 'buildozer.spec'               #: gui app build config file

DOTENV_FILENAME = '.env'                        #: name of the file containing console/shell environment variables
DOTENV_LINE_MATCHER = re.compile(r"""
    ^
    (?:export\s+)?          # optional export
    ([\w.]+)                # env variable name
    (?:\s*=\s*|:\s+?)       # separator
    (                       # optional value begin
        '(?:\'|[^'])*'      #   single quoted value
        |                   #   or
        "(?:\"|[^"])*"      #   double quoted value
        |                   #   or
        [^#\n]+             #   unquoted value
    )?                      # value end
    (?:\s*\#.*)?            # optional comment
    $
    """, re.VERBOSE)
DOTENV_VAR_IN_VAL_MATCHER = re.compile(r"""
    (\\)?                   # is it escaped with a backslash? (env variable name matcher groups item 0 | evn_groups[0])
    (\$)                    # literal $ (matcher evn_groups[1])
    (                       # group for easier subsitution via evn_groups[0:-1] (matcher evn_groups[2])
        \{?                 #   allow brace wrapping
        ([A-Za-z0-9_]+)     #   match var name; allowing lowercase letters in env var names (matcher evn_groups[3|-1]
        }?                  #   closing brace
    )                       # braces end
    """, re.IGNORECASE | re.VERBOSE)

MODULE_NAME_SEPS = ('_', '.', '-')                      #: separators considered equivalent for comparison (:pep:`503`)
MODULE_NAME_PATTERN = re.compile("[" + "".join(MODULE_NAME_SEPS) + "]+")  # escape hyphen/'\-' if not first/last chr

PYPI_PACKAGE_NAMES = {
    'absl': 'absl-py',
    'airflow': 'apache-airflow',
    'allauth': 'django-allauth',
    'apt': 'python-apt',
    'arango': 'python-arango',
    'attr': 'attrs',
    'Bio': 'biopython',
    'bootstrap5': 'django-bootstrap5',
    'bs4': 'beautifulsoup4',
    'bson': 'pymongo',                                  # pymongo extension
    'cassandra': 'cassandra-driver',
    'cms': 'django-cms',
    'consul': 'python-consul',
    'corsheaders': 'django-cors-headers',
    'crispy_forms': 'django-crispy-forms',
    'crontab': 'python-crontab',
    'Crypto': 'pycryptodome',
    'cups': 'pycups',
    'cv2': 'opencv-python',
    'dateutil': 'python-dateutil',
    'dbus': 'dbus-python',
    'discord': 'discord.py',
    'dns': 'dnspython',
    'docx': 'python-docx',
    'dotenv': 'python-dotenv',
    'engineio': 'python-engineio',
    'faiss': 'faiss-cpu',                               # alternativ faiss-gpu
    'ffmpeg': 'ffmpeg-python',
    'filer': 'django-filer',
    'fitz': 'PyMuPDF',
    'fpdf': 'fpdf2',
    'gi': 'PyGObject',
    'git': 'GitPython',
    'github': 'PyGithub',
    'gitlab': 'python-gitlab',
    'gnupg': 'python-gnupg',
    'googleapiclient': 'google-api-python-client',
    'google.oauth2': 'google-auth',
    'google.protobuf': 'protobuf',
    'gridfs': 'pymongo',                                # pymongo extension
    'gtk': 'PyGTK',
    'haystack': 'django-haystack',
    'igraph': 'python-igraph',
    'jnius': 'pyjnius',
    'jose': 'python-jose',
    'jwt': 'PyJWT',
    'kafka': 'kafka-python',
    'ldap': 'python-ldap',
    'Levenshtein': 'python-Levenshtein',
    'magic': 'python-magic',
    'memcache': 'python-memcached',
    'menus': 'django-cms',                              # django-cms extension
    'multipart': 'python-multipart',
    'mysql': 'mysql-connector-python',
    'MySQLdb': 'mysqlclient',
    'nacl': 'PyNaCl',
    'nmap': 'python-nmap',
    'odf': 'odfpy',
    'OpenGL': 'PyOpenGL',
    'opensearchpy': 'opensearch-py',
    'OpenSSL': 'pyOpenSSL',
    'paho': 'paho-mqtt',
    'parler': 'django-parler',
    'PIL': 'pillow',
    'playhouse': 'peewee',                              # peewee extension
    'pptx': 'python-pptx',
    'psycopg2': 'psycopg2-binary',
    'pywt': 'PyWavelets',
    'rest_framework': 'djangorestframework',
    'RPi': 'RPi.GPIO',
    'rtmidi': 'python-rtmidi',
    'ruamel': 'ruamel.yaml',
    'sekizai': 'django-sekizai',
    'serial': 'pyserial',
    'skimage': 'scikit-image',
    'sklearn': 'scikit-learn',
    'slugify': 'python-slugify',
    'smbus': 'smbus2',
    'snappy': 'python-snappy',
    'socketio': 'python-socketio',
    'speech_recognition': 'SpeechRecognition',
    'storages': 'django-storages',
    'telegram': 'python-telegram-bot',
    'treebeard': 'django-treebeard',
    'usb': 'pyusb',
    'usb1': 'libusb1',
    'vlc': 'python-vlc',
    'websocket': 'websocket-client',
    'whois': 'python-whois',
    'win32api': 'pywin32',
    'win32com': 'pywin32',
    'wx': 'wxPython',
    'xlib': 'python-xlib',
    'yaml': 'PyYAML',
    'zmq': 'pyzmq',
}
""" irregular project/package names; not convertable from their import names. """

SKIPPED_MODULES = ('ae.base', 'ae.system', 'ae.files', 'ae.paths', 'ae.dynamicod',
                   'ae.core', 'ae.console', 'ae.snell', 'ae.managed_files',
                   'ae.gui', 'ae.gui.app', 'ae.gui.tours', 'ae.gui.utils',
                   'ae.kivy', 'ae.kivy.apps', 'ae.kivy.behaviors', 'ae.kivy.i18n', 'ae.kivy.tours', 'ae.kivy.widgets',
                   'ae.enaml_app', 'ae.toga_app', 'ae.pyglet_app', 'ae.pygobject_app', 'ae.dabo_app',
                   'ae.qpython_app', 'ae.appjar_app',
                   'importlib._bootstrap', 'importlib._bootstrap_external')
""" skipped modules used as default by :func:`stack_var` and :func:`stack_vars` """


EnvVarsType = MutableMapping[str, str]               #: environment variables dict/mapping
EnvVarsLateResolvedType = dict[str, list[tuple[str, str, str, str]]]     #: mapping of DOTENV_VAR_IN_VAL_MATCHER results


def app_name_guess() -> str:
    """ guess/try to determine the name of the currently running app (w/o assessing not yet initialized app instance).

    :return:                    application name/id or "unguessable" if not guessable.
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
                                in the :data:`APP_BUILD_CFG_FILENAME` spec file or if this file does not exist in cwd).
    """
    if not os_path_isfile(APP_BUILD_CFG_FILENAME):
        return tuple(def_val for name, def_val in names_defaults)

    config = instantiate_config_parser()
    config.read(APP_BUILD_CFG_FILENAME, 'utf-8')

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
                    val = repr(val).replace(os.linesep, "\\n")
                    ret += ' ' * 6 + f"= {nam}: {val}" + os.linesep

    return ret


def instantiate_config_parser() -> ConfigParser:
    """ instantiate and prepare config file parser.

    ensures that the :class:`~configparser.ConfigParser` instance is correctly configured, e.g., to support
    case-sensitive config variable names and to use :class:`ExtendedInterpolation` as the interpolation argument.
    """
    cfg_parser = ConfigParser(allow_no_value=True, interpolation=ExtendedInterpolation())
    # set optionxform to have case-sensitive var names (or use 'lambda option: option')
    # mypy V 0.740 bug - see mypy issue #5062: adding pragma "type: ignore" breaks PyCharm (showing
    # inspection warning "Non-self attribute could not be type-hinted"), but
    # also cast(Callable[[Arg(str, 'option')], str], str) and # type: ... is not working
    # (because Arg is not available in plain mypy, only in the extra mypy_extensions package)
    setattr(cfg_parser, 'optionxform', str)
    return cfg_parser


def late_env_var_resolver(env_vars: EnvVarsType, loaded_vars: EnvVarsType, late_resolved: EnvVarsLateResolvedType):
    """ late resolve/expand/substitute of env variables in env var values.

    :param env_vars:            all cached environment variables (preferred to os.environ), will get substituted.
                                also used to search&resolve env var values (if not found then searched in os.environ).
    :param loaded_vars:         recently loaded environment variables, will get substituted.
    :param late_resolved:       matches of loaded env vars to be resolved late (after all env vars got detected and
                                loaded). the key of this dict is the name of the env variable which has other env vars
                                in its values to be resolved/substituted. the item value of this dict is a list of
                                matcher group tuples for each found env variable. the group/tuple items are
                                (0) escape character, (1) the dollar character, (2) the env var name literal (optionally
                                in curly brackets) and (3/-1) the env var name.
    """
    retries = len(late_resolved)                            # retry if later-/not-yet-replaced env var in env var value
    while late_resolved and retries:                        # pylint: disable=too-many-nested-blocks
        for var_nam, matches in late_resolved.copy().items():
            # substitute declared and not escaped env variables found via :data:`DOTENV_VAR_IN_VAL_MATCHER` in a value
            for evn_groups in matches.copy():   # try to replace env vars with its values, removed from matches
                # noinspection PyUnresolvedReferences
                if evn_groups[0] == '\\':                               # if escaped '$' character
                    replace: str | None = "".join(evn_groups[1:-1])  # then only unescape (no var search&substitute)
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
                        retries += len(replacement_matches)

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
        only variables that are not already defined in the OS environment variables mapping :data:`os.environ` will be
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
                                into the  specified :paramref:`~load_env_var_defaults.env_vars` mapping if they are not
                                already there. after processing the first ``.env`` file, it repeats to check for
                                further ``.env`` files in the parent folder to load them too, until either detecting
                                a folder without an ``.env`` file or until an ``.env`` got loaded from the root folder.
    :param env_vars:            environment variables mapping to be amended with env variable values from any
                                found ``.env`` file. pass Python's :data:`os.environ` to amend this mapping directly
                                with all the already not declared environment variables.
    :return:                    env var names (keys) and values added to :paramref:`~load_env_var_defaults.env_vars`.
    """
    start_dir = norm_path(start_dir)
    file_path = os_path_join(start_dir, DOTENV_FILENAME)
    if not os_path_isfile(file_path):
        file_path = os_path_join(os_path_dirname(start_dir), DOTENV_FILENAME)

    loaded_vars = {}
    late_resolved: EnvVarsLateResolvedType = {}
    while os_path_isfile(file_path):
        for var_nam, var_val in parse_dotenv(file_path, late_resolved, exclude_vars=env_vars).items():
            env_vars[var_nam] = loaded_vars[var_nam] = var_val

        if os.sep not in file_path:
            break           # pragma: no cover # prevent endless-loop for ``.env`` file in root dir (os.sep == "/")
        file_path = os_path_join(os_path_dirname(os_path_dirname(file_path)), DOTENV_FILENAME)

    late_env_var_resolver(env_vars, loaded_vars, late_resolved)

    return loaded_vars


def main_file_paths_parts(portion_name: str) -> tuple[tuple[str, ...], ...]:
    """ determine possible/supported main/version file name and path parts, relative to the project root folder.

    :param portion_name:        portion or package name.
    :return:                    tuple of tuples of main/version file name path parts.
    """
    base_layouts = (
        (PY_INIT, ),                                                            # flat layouts
        (PY_MAIN, ),
        ('main' + PY_EXT, ),
        ('main', PY_INIT),
        (portion_name + PY_EXT, ),
        (portion_name, PY_INIT),                                                # top-level layouts (e.g. Django)
        (portion_name, PY_MAIN),
    )
    return base_layouts + tuple(("src", ) + layout for layout in base_layouts)  # base layouts + src layouts


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
    if not file_path:                                   # pragma: no cover
        try:
            # noinspection PyProtectedMember,PyUnresolvedReferences
            file_path = sys._getframe().f_back.f_code.co_filename   # type: ignore # pylint: disable=protected-access
        except (AttributeError, Exception):                         # pylint: disable=broad-except # pragma: no cover
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
            elif spec.submodule_search_locations:           # pragma: no cover
                path = spec.submodule_search_locations[0]   # take 1st dir of Namespace package with multiple locations
            else:
                errors.append(f"path not available for {spec.origin or ""} module {import_name}")  # pragma: no cover
        else:
            path = spec.origin
    except (ValueError, Exception) as exc:  # pragma: no cover # pylint: disable=broad-exception-caught
        errors.append(f"find_spec({import_name=}) raised {exc=}")

    return errors or path


def module_load(import_name: str, path: str | UnsetType | None = UNSET) -> ModuleType | list[str]:
    """ search, import and execute a Python module dynamically without adding it to sys.modules.

    :param import_name:         dot-name of the module to import.
    :param path:                optional file path of the module to import. if this arg is not specified or has the
                                default value (:data:`UNSET`), then the path will be determined from the import name.
                                specify ``None`` to prevent the module search.
    :return:                    a reference to the module if the module could be loaded, else a list of error strings.
    """
    errors: list[str] = []

    if path is UNSET:
        py_mo = PyMo(import_name)
        if not os_path_isfile(path := py_mo.module_file_path) and not os_path_isfile(path := py_mo.package_file_path):
            path = _path_or_err if isinstance(_path_or_err := module_find(import_name), str) else None

    mod_ref: ModuleType | list[str] = [f"unexpected error in load of module {import_name}"]
    # noinspection PyUnnecessaryCast
    spec = importlib.util.spec_from_file_location(import_name, cast(str | None, path), submodule_search_locations=[])
    if isinstance(spec, ModuleSpec):
        try:
            mod_ref = importlib.util.module_from_spec(spec)
            # added isinstance calls to suppress PyCharm+mypy inspections
            if isinstance(spec.loader, importlib.abc.Loader) and isinstance(mod_ref, ModuleType):
                spec.loader.exec_module(mod_ref)
            else:
                errors.append(f"spec.loader ({type(spec.loader)=} is not of importlib.abs.loader")  # pragma: no cover
        except (FileNotFoundError, Exception) as exc:   # pragma: no cover # pylint: disable=broad-exception-caught
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


def os_host_name() -> str:
    """ determine the operating system host/machine name.

    :return:                    machine name string.
    """
    return defuse(platform.node()) or "indeterminableHostName"


# noinspection PyTypeChecker
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
    except (OSError, IOError, Exception):                           # pylint: disable=broad-except # pragma: no cover
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
                                * `'linux'` for all other unix systems (like Arch, Debian/Ubuntu, Suse, ...).
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
if os_platform == 'android':                                        # pragma: no cover
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


elif os_platform in ('win32', 'cygwin'):                            # pragma: no cover
    if _dev_id := os.environ.get('COMPUTERNAME'):
        os_device_id = defuse(_dev_id)


def os_user_name() -> str:
    """ determine the operating system username.

    :return:                    username string.
    """
    return getpass.getuser()


def parse_dotenv(file_path: str, late_resolved: EnvVarsLateResolvedType, exclude_vars: Container = ()) -> EnvVarsType:
    """ parse ``.env`` file content and return environment variable names as dict keys and values as dict values.

    :param file_path:           string with the name/path of an existing ``.env``/:data:`DOTENV_FILENAME` file.
    :param late_resolved:       mapping extended with matches of env vars found in the returned env var values.
    :param exclude_vars:        names of env vars to preserve their value (do not return).
    :return:                    mapping with parsed environment variable names and values.
    """
    lines = []          # unwrap multi-line .env variable values with backslash at line end (Docker/UNIX-style format)
    prev_lines = ""
    # noinspection PyUnnecessaryCast
    for line in cast(str, read_file(file_path)).splitlines():
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
                warnings.warn(f"'{line!r}' in '{file_path}' doesn't match {DOTENV_FILENAME} format", SyntaxWarning)
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


def project_main_file(import_name: str, project_path: str = "") -> str:
    """ determine the main module file path of a project package containing the project __version__ module variable.

    :param import_name:         name of the module/package (including namespace prefixes, separated with dots).
    :param project_path:        optional path where the project of the package/module is situated. not needed if the
                                current working directory is the root folder of either the import_name project or of a
                                sister project (under the same project parent folder).
    :return:                    absolute file path of the main module or empty string if no main/version file is found.
    """
    *namespace_dirs, portion_name = PyMo(import_name).name_parts
    project_name = ('_'.join(namespace_dirs) + '_' if namespace_dirs else "") + portion_name
    paths_parts = main_file_paths_parts(portion_name)

    project_path = norm_path(project_path)
    module_paths = []
    if os_path_basename(project_path) != project_name:
        module_paths.append(os_path_join(os_path_dirname(project_path), project_name, *namespace_dirs))
    if namespace_dirs:
        module_paths.append(os_path_join(project_path, *namespace_dirs))
    module_paths.append(project_path)

    for module_path in module_paths:
        for path_parts in paths_parts:
            main_file = os_path_join(module_path, *path_parts)
            if os_path_isfile(main_file):
                # noinspection PyTypeChecker
                return main_file
    return ""


def stack_frames(depth: int = 1) -> Generator:  # Generator[frame, None, None]
    """ generator returning the call stack frame from the level given in :paramref:`~stack_frames.depth`.

    :param depth:               the stack level to start; the first returned frame by this generator. the default value
                                (1) refers to the next deeper stack frame, respectively the one of the caller of this
                                function. pass 2 or a higher value if you want to start with an even deeper frame/level.
    :return:                    generated frames of the call stack.
    """
    try:
        while True:
            depth += 1
            # noinspection PyProtectedMember,PyUnresolvedReferences
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
    :param scope:               scope to search the variable name passed via :paramref:`~stack_vars.find_name`. pass
                                'locals' to only search for local variables (ignoring globals) or 'globals' to only
                                check for global variables (ignoring locals). passing an empty string will find the
                                variable within either locals or globals.
    :param min_depth:           the call stack level from which on to search. the default value (1) refers the next
                                deeper stack frame, respectively, to the caller of this function. pass 2 or a higher
                                value if you want to get the variables from a deeper level in the call stack.
    :param max_depth:           the maximum depth in the call stack from which to return the variables. if the specified
                                argument is not zero and no :paramref:`~stack_vars.skip_modules` are specified, then the
                                first deeper stack frame that is not within the default :data:`SKIPPED_MODULES` will be
                                returned. if this argument and :paramref:`~stack_vars.find_name` get not passed,
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
        'os env': mask_secrets(os.environ.copy()),
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


class PyMo(ErrorMsgMixin):
    """ helper class to create, represent, inspect, load or import a Python module or package. """
    def __init__(self, import_name: str, project_path: str = "", **pypi_names: str) -> None:
        """ create a new instance of the class :class:`PyMo`.

        :param import_name:     import name of the module/package/portion.
        :param project_path:    optional project root folder path.
        :param pypi_names:      irregular PyPI project/distribution names; not convertable from their import names
                                (key_word==import name; value==PyPi distribution/project name). if the import name
                                contains a dot-character then specify this value as ``**dict``.
        """
        super().__init__()
        if not import_name:
            self.error_message = "Erroneous PyMo instance created with empty import name"

        self.import_name = import_name or 'import.name.error'
        self._project_path = project_path
        self._pypi_names = PYPI_PACKAGE_NAMES.copy()
        self._pypi_names.update(**pypi_names)

    @classmethod
    def from_name(cls, name: str, namespace_name: str = "", project_path: str = "", **pypi_names: str) -> Self:
        """ create a :class:`PyMo` instance from the name of a project/package/portion/module.

        :param name:            import/pip/package/project name of the module/package/portion.
        :param namespace_name:  namespace name/path w/ or w/o the module/portion name (at the end).
        :param project_path:    root folder path of the source project.
        :param pypi_names:      irregular PyPI project/distribution names; not convertable from their import names
                                (key_word==import name; value==PyPi distribution/project name).
        :return:                PyMo instance of the Python module/package/portion. specifying invalid arguments results
                                in an instance with an :attr:`~PyMo.import_name+` of 'import.name.error'.
        """
        name = (name or 'import.name.error').replace('-', '_')

        if namespace_name:
            import_name = ""
            for namespace_part in namespace_name.split('.'):
                if not name.startswith((namespace_part + '.', namespace_part + '_')):
                    break
                name = name[len(namespace_part) + 1:]
                import_name += namespace_part + '.'
            import_name += name
        else:
            import_name = name

        return cls(import_name, project_path=project_path, **pypi_names)

    @classmethod
    def from_path(cls, project_path: str, namespace_name: str = "", **pypi_names: str) -> Self:
        """ create a :class:`PyMo` instance from the specified project-root folder (source-code) path.

        :param project_path:    root folder path of the project source code.
        :param namespace_name:  namespace name/path with or without the module/portion name.
        :param pypi_names:      irregular PyPI project/distribution names; not convertable from their import names
                                (key_word==import name; value==PyPi distribution/project name).
        :return:                PyMo instance of the Python module/package/portion.
        """
        project_path = norm_path(project_path)
        project_name = os_path_basename(project_path)
        if namespace_name:
            return cls.from_name(project_name, namespace_name=namespace_name, project_path=project_path)

        import_name = project_name
        name_parts = MODULE_NAME_PATTERN.split(project_name)
        joints = len(name_parts) - 1
        if joints >= 1:
            combinations = itertools.product(("/", ) + MODULE_NAME_SEPS, repeat=joints)
            for combo in combinations:
                name = "".join(name_parts[i] + combo[i] for i in range(joints)) + name_parts[-1]
                *namespace_parts, portion_name = name.rsplit("/", maxsplit=1)
                for path_parts in main_file_paths_parts(portion_name):
                    if os_path_isfile(os_path_join(project_path, *namespace_parts, *path_parts)):
                        import_name = name.replace("/", '.')
                        break

        return cls(import_name.replace('-', '_'), project_path=project_path, **pypi_names)

    def __repr__(self):
        return f"PyMo('{self.import_name}', project_path='{self._project_path}', pypi_names={self._pypi_names})"

    def _warn(self, msg: str):
        self.error_message = f"{self.__class__.__name__}({self.import_name}) {msg}"

    @property
    def imported_module(self) -> ModuleType | None:
        """ try to import module, add it to sys.modules and return the spec of it (or None if not found/imported). """
        if self.import_name in sys.modules:
            return sys.modules[self.import_name]

        try:
            return importlib.import_module(self.import_name)
        except (ImportError, ModuleNotFoundError, Exception) as exc:  # pylint: disable=broad-exception-caught
            self._warn(f"imported_module raised {exc=}")

        return None

    @property
    def loaded_module(self) -> ModuleType | None:
        """ try to load module (without adding it to sys.modules). return the spec of it or None if not found. """
        mod_ref = module_load(self.import_name)
        if not isinstance(mod_ref, ModuleType):
            if self._project_path:
                mod_ref = module_load(self.import_name, path=self.package_file_path)
                if not isinstance(mod_ref, ModuleType):
                    mod_ref = module_load(self.import_name, path=self.module_file_path)

            if not isinstance(mod_ref, ModuleType):
                self.error_message = "\n".join(mod_ref)
                return None
        return mod_ref

    @property
    def module_file_path(self) -> str:
        """ module file path (absolute if project_path got specified, else relative to the project root folder). """
        return os_path_join(self._project_path, *self.name_parts) + PY_EXT

    @property
    def namespace_name(self) -> str:
        """ namespace name/path of the Python module/package represented by this instance. """
        return '.'.join(self.name_parts[:-1])

    @property
    def name_parts(self) -> list[str]:
        """ module-/portion-name parts of the Python module, including namespace name prefix(es). """
        return self.import_name.split('.')

    @property
    def package_name(self) -> str:
        """ name of the package/project of the Python module. """
        return '_'.join(self.name_parts)

    @property
    def package_file_path(self) -> str:
        """ package path w/ PY_INIT (and project_path if specified, else relative to the project root folder). """
        return os_path_join(self._project_path, *self.name_parts, PY_INIT)

    @property
    def pip_name(self) -> str:
        """ pip&PyPI package name of the Python module. """
        return norm_pip_name(self.project_name)

    @property
    def portion_name(self) -> str:
        """ name of the Python module """
        return self.name_parts[-1]

    @property
    def project_name(self) -> str:
        """ name of the Python distribution/project (could differ from the :attr:`~PyMo.package_name` property). """
        return self._pypi_names.get(self.import_name, self.package_name)

    @property
    def project_root_path(self) -> str:
        """ normalized absolute project root path of the Python module. """
        return norm_path(self._project_path or self.package_name)
