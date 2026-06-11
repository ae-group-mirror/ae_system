""" ae.system unit tests. """
import os
import sys
import tempfile
import textwrap
import warnings

from configparser import ConfigParser
from types import ModuleType
from typing import cast

import pytest

from tests.conftest import skip_gitlab_ci

from ae.base import (
    DEF_PROJECT_PARENT_FOLDER, PY_EXT, PY_INIT, PY_MAIN, TESTS_FOLDER, UNSET,
    norm_path, os_path_dirname, os_path_isdir, os_path_join, write_file, os_path_basename)


# noinspection PyProtectedMember
from ae.system import (
    APP_BUILD_CFG_FILENAME, DOTENV_FILENAME, DOTENV_VAR_IN_VAL_MATCHER,
    app_name_guess, build_config_variable_values, full_stack_trace, instantiate_config_parser,
    late_env_var_resolver, load_dotenvs, load_env_var_defaults, main_file_paths_parts,
    module_attr, module_find, module_load, module_file_path,
    os_host_name, os_local_ip, _os_platform, os_user_name,
    parse_dotenv, project_main_file,
    stack_frames, stack_var, stack_vars, sys_env_dict, sys_env_text,
    PyMo)


module_test_var = 'module_test_var_val'   # used for stack_var()/try_exec() tests


DOTENV_VAR_NAME = 'env_var_nam1'
DOTENV_VAR_VAL = 'value of env var'
DOTENV_LATE_VAR_PRE = 'late_var_nam'
DOTENV_LATE_VAL_PRE = '-late Pre Val'
DOTENV_DIR_NAME = 'fdr'
DOTENV_FULL_DIRS = (0, 1, 3)
DOTENV_DIR_RANGE = 6
DOTENV_LIT_VALUES = {}
DOTENV_LATE_VALUES = {}
for _level in range(DOTENV_DIR_RANGE):
    if _level in DOTENV_FULL_DIRS:
        _val_lit = "".join("$" + ("{" if _ % 2 else "") + DOTENV_LATE_VAR_PRE + str(_) + ("}" if _ % 2 else "")
                           for _ in range(_level) if _ in DOTENV_FULL_DIRS)
        DOTENV_LIT_VALUES[_level] = DOTENV_LATE_VAL_PRE + _val_lit + "  " + str(_level)
        DOTENV_LATE_VALUES[_level] = DOTENV_LATE_VAL_PRE + "".join(
                DOTENV_LATE_VALUES[_var_level] for _var_level in range(_level) if _var_level in DOTENV_FULL_DIRS
            ) + "  " + str(_level)


@pytest.fixture
def os_env_test_env():
    """ create .env files to test and backup os.environ. """
    with tempfile.TemporaryDirectory() as tmp_path:
        for level in range(DOTENV_DIR_RANGE):
            file_path = os.path.join(tmp_path, *((DOTENV_DIR_NAME, ) * level))
            os.makedirs(file_path, exist_ok=True)
            if level in DOTENV_FULL_DIRS:
                content = (os.linesep + DOTENV_VAR_NAME + "='" + DOTENV_VAR_VAL + str(level) + "'" +
                           os.linesep + DOTENV_LATE_VAR_PRE + str(level) + '="' + DOTENV_LIT_VALUES[level] + '"' +
                           os.linesep + "RecursiveWithLowerCase = $RecursiveWithLowerCase")
                write_file(os.path.join(file_path, DOTENV_FILENAME), content)

        old_env = os.environ
        os.environ = old_env.copy()

        yield tmp_path

        os.environ = old_env


class TestHelpers:
    def test_app_name_guess(self):
        assert app_name_guess()     # app.exe name in pytest returning '_jb_pytest_runner'(PyCharm)/'__main__'(console)
        assert app_name_guess() != 'main'
        assert app_name_guess() == 'unguessable'

    def test_build_config_variable_values_with_spec(self):
        try:
            with open(APP_BUILD_CFG_FILENAME, "w") as file_handle:
                file_handle.write("""[app]\nexisting = tst""")
            existing, not_existing = build_config_variable_values(
                ('existing', ""),
                ('not_existing', "default_value")
            )
            assert existing == "tst"
            assert not_existing == "default_value"
        finally:
            if os.path.exists(APP_BUILD_CFG_FILENAME):
                os.remove(APP_BUILD_CFG_FILENAME)

    def test_build_config_variable_values_no_spec(self):
        assert not os.path.exists(APP_BUILD_CFG_FILENAME)
        existing, not_existing = build_config_variable_values(
            ('not_existing1', "default_value1"),
            ('not_existing2', "default_value2")
        )
        assert existing == "default_value1"
        assert not_existing == "default_value2"

    def test_instantiate_config_parser(self):
        cfg_parser = instantiate_config_parser()
        assert isinstance(cfg_parser, ConfigParser)
        assert cfg_parser.optionxform is str

    def test_late_env_var_resolver_errors_and_warnings(self):
        # all branches in this follow-up/resolve function are already covered by the test_load_env_var_defaults*() tests
        late_env_var_resolver({}, {}, {})

        with warnings.catch_warnings(record=True) as warnings_list:

            late_env_var_resolver({}, {}, {'unresolvable_var': [('', '$', '{NOT_EXISTENT_VAR}', 'NOT_EXISTENT_VAR')]})

            assert warnings_list is not None
            assert len(warnings_list) == 1
            assert "has unresolved environment variables in its value" in str(warnings_list[0].message)

        with warnings.catch_warnings(record=True) as warnings_list:
            var_nam = "RECURSIVE_VAR_Name"
            var_val = "infinite-val-grow$" + var_nam
            late_resolved = {var_nam: DOTENV_VAR_IN_VAL_MATCHER.findall(var_val)}
            env_vars = {var_nam: var_val}

            late_env_var_resolver(env_vars, env_vars, late_resolved)

            assert warnings_list is not None
            assert len(warnings_list) == 1
            assert "ignoring recursive environment variable" in str(warnings_list[0].message)

    def test_load_dotenvs(self, os_env_test_env):
        assert DOTENV_VAR_NAME not in os.environ
        load_dotenvs()
        assert DOTENV_VAR_NAME not in os.environ

    def test_load_dotenvs_from_module_path(self, os_env_test_env):
        assert DOTENV_VAR_NAME not in os.environ
        load_dotenvs(from_module_path=True)
        assert DOTENV_VAR_NAME not in os.environ

    def test_load_env_var_defaults_errors(self):
        with pytest.raises(TypeError):
            # noinspection PyArgumentList
            load_env_var_defaults()

        with pytest.raises(TypeError):
            # noinspection PyTypeChecker
            load_env_var_defaults(None, None)   # STRANGE: raising TypeError in Python 3.9.21/local but not in 3.9.23/CI
            # noinspection PyArgumentList
            load_env_var_defaults(None)         # HOTFIX ensuring failure - could not find any changelog notes

        # noinspection PyTypeChecker
        load_env_var_defaults("inv:_ file path", ())  # NO ERROR EXCEPTIONS on these invalid arg values!!!

    def test_load_env_var_defaults_not_loaded(self):
        env_vars = {}

        load_env_var_defaults('/', env_vars)
        assert DOTENV_VAR_NAME not in env_vars

        load_env_var_defaults('.', env_vars)
        assert DOTENV_VAR_NAME not in env_vars

    def test_load_env_var_defaults_not_loaded_in_os_environ(self, os_env_test_env):
        assert DOTENV_VAR_NAME not in os.environ

        load_env_var_defaults('/', os.environ)
        assert DOTENV_VAR_NAME not in os.environ

        load_env_var_defaults('.', os.environ)
        assert DOTENV_VAR_NAME not in os.environ

        load_env_var_defaults(os.path.join(os_env_test_env, *((DOTENV_DIR_NAME,) * 5)), os.environ)
        assert DOTENV_VAR_NAME not in os.environ

        load_env_var_defaults(os.path.join(os_env_test_env, *((DOTENV_DIR_NAME,) * 6)), os.environ)  # too-deep path
        assert DOTENV_VAR_NAME not in os.environ

    def test_load_env_var_defaults_load_start_parent_first_no_chain(self, monkeypatch, os_env_test_env):
        monkeypatch.chdir(os.path.join(os_env_test_env, *((DOTENV_DIR_NAME,) * 4)))

        loaded = load_env_var_defaults("", os.environ)

        assert DOTENV_VAR_NAME in loaded
        assert loaded[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '3'
        assert DOTENV_VAR_NAME in os.environ
        assert os.environ[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '3'

    def test_load_env_var_defaults_load_start_first_no_chain(self, os_env_test_env):
        loaded = load_env_var_defaults(os.path.join(os_env_test_env, *((DOTENV_DIR_NAME,) * 3)), os.environ)

        assert DOTENV_VAR_NAME in loaded
        assert loaded[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '3'
        assert DOTENV_VAR_NAME in os.environ
        assert os.environ[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '3'

    def test_load_env_var_defaults_load_start_parent_first_in_chain(self, os_env_test_env):
        loaded = load_env_var_defaults(os.path.join(os_env_test_env, *((DOTENV_DIR_NAME,) * 2)), os.environ)

        assert DOTENV_VAR_NAME in loaded
        assert loaded[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '1'
        assert DOTENV_VAR_NAME in os.environ
        assert os.environ[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '1'

    def test_load_env_var_defaults_load_start_no_parent_first_in_chain(self, os_env_test_env):
        loaded = load_env_var_defaults(os.path.join(os_env_test_env, *((DOTENV_DIR_NAME,) * 1)), os.environ)

        assert DOTENV_VAR_NAME in loaded
        assert loaded[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '1'
        assert DOTENV_VAR_NAME in os.environ
        assert os.environ[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '1'

    def test_load_env_var_defaults_load_start_on_second_within_chain(self, os_env_test_env):
        loaded = load_env_var_defaults(os.path.join(os_env_test_env, *((DOTENV_DIR_NAME,) * 0)), os.environ)

        assert DOTENV_VAR_NAME in loaded
        assert loaded[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '0'
        assert DOTENV_VAR_NAME in os.environ
        assert os.environ[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '0'

    def test_load_env_var_defaults_resolve_vars_late(self, os_env_test_env):
        loaded = load_env_var_defaults(os.path.join(os_env_test_env, *((DOTENV_DIR_NAME,) * 1)), os.environ)

        assert DOTENV_LATE_VAR_PRE + '0' in loaded
        assert DOTENV_LATE_VAR_PRE + '0' in os.environ
        assert DOTENV_LATE_VAR_PRE + '1' in loaded
        assert DOTENV_LATE_VAR_PRE + '1' in os.environ
        assert DOTENV_LATE_VAR_PRE + '3' not in loaded
        assert DOTENV_LATE_VAR_PRE + '3' not in os.environ
        assert loaded[DOTENV_LATE_VAR_PRE + '0'] == DOTENV_LATE_VALUES[0]
        assert os.environ[DOTENV_LATE_VAR_PRE + '0'] == DOTENV_LATE_VALUES[0]
        assert loaded[DOTENV_LATE_VAR_PRE + '1'] == DOTENV_LATE_VALUES[1]
        assert os.environ[DOTENV_LATE_VAR_PRE + '1'] == DOTENV_LATE_VALUES[1]

    def test_load_env_var_defaults_resolve_vars_late_with_gap_and_closed_gap(self, os_env_test_env):
        empty_env = {}

        loaded = load_env_var_defaults(os.path.join(os_env_test_env, *((DOTENV_DIR_NAME, ) * 3)), empty_env)

        assert DOTENV_LATE_VAR_PRE + '0' not in loaded
        assert DOTENV_LATE_VAR_PRE + '0' not in empty_env
        assert DOTENV_LATE_VAR_PRE + '1' not in loaded
        assert DOTENV_LATE_VAR_PRE + '1' not in empty_env
        assert DOTENV_LATE_VAR_PRE + '3' in loaded
        assert DOTENV_LATE_VAR_PRE + '3' in empty_env
        assert loaded[DOTENV_LATE_VAR_PRE + '3'] == DOTENV_LIT_VALUES[3]
        assert empty_env[DOTENV_LATE_VAR_PRE + '3'] == DOTENV_LIT_VALUES[3]

        write_file(os.path.join(os_env_test_env, *((DOTENV_DIR_NAME, ) * 2), DOTENV_FILENAME), "# closing level 2 gap")

        loaded = load_env_var_defaults(os.path.join(os_env_test_env, *((DOTENV_DIR_NAME, ) * 3)), os.environ)

        assert DOTENV_LATE_VAR_PRE + '0' in loaded
        assert DOTENV_LATE_VAR_PRE + '0' in os.environ
        assert DOTENV_LATE_VAR_PRE + '1' in loaded
        assert DOTENV_LATE_VAR_PRE + '1' in os.environ
        assert DOTENV_LATE_VAR_PRE + '3' in loaded
        assert DOTENV_LATE_VAR_PRE + '3' in os.environ
        assert loaded[DOTENV_LATE_VAR_PRE + '3'] == DOTENV_LATE_VALUES[3]
        assert os.environ[DOTENV_LATE_VAR_PRE + '3'] == DOTENV_LATE_VALUES[3]

    def test_main_file_paths_parts(self):
        assert isinstance(main_file_paths_parts(""), tuple)
        assert len(main_file_paths_parts(""))
        assert isinstance(main_file_paths_parts("")[0], tuple)

        assert ('main' + PY_EXT, ) in main_file_paths_parts("")
        assert any(PY_MAIN in _ for _ in main_file_paths_parts(""))
        assert any(PY_INIT in _ for _ in main_file_paths_parts(""))

        por_name = "portion_tst_name"
        assert ('main' + PY_EXT, ) in main_file_paths_parts(por_name)
        assert (por_name, PY_INIT) in main_file_paths_parts(por_name)
        assert any(por_name in _ for _ in main_file_paths_parts(por_name))
        assert any(por_name + PY_EXT in _ for _ in main_file_paths_parts(por_name))

    def test_os_host_name(self):
        print(os_host_name())
        assert os_host_name()

    def test_os_local_ip(self):
        assert os_local_ip() or os_local_ip() == ""

    def test_os_platform_android(self):
        try:
            os.environ['ANDROID_ARGUMENT'] = 'tst'
            assert _os_platform() == 'android'
        finally:
            os.environ.pop('ANDROID_ARGUMENT', None)

        # noinspection PyUnreachableCode
        try:
            os.environ['KIVY_BUILD'] = 'android'
            assert _os_platform() == 'android'
        finally:
            os.environ.pop('KIVY_BUILD', None)

    def test_os_platform_cygwin(self):
        old_platform = sys.platform
        try:
            sys.platform = 'cygwin'
            assert _os_platform() == 'cygwin'
        finally:
            sys.platform = old_platform

    def test_os_platform_darwin(self):
        old_platform = sys.platform
        try:
            sys.platform = 'darwin'
            assert _os_platform() == 'darwin'
        finally:
            sys.platform = old_platform

    def test_os_platform_freebsd(self):
        old_platform = sys.platform
        try:
            sys.platform = 'freebsd'
            assert _os_platform() == 'freebsd'
        finally:
            sys.platform = old_platform

    def test_os_platform_ios(self):
        try:
            os.environ['KIVY_BUILD'] = 'ios'
            assert _os_platform() == 'ios'
        finally:
            os.environ.pop('KIVY_BUILD', None)

    def test_os_platform_win32(self):
        old_platform = sys.platform
        try:
            sys.platform = 'win32'
            assert _os_platform() == 'win32'
        finally:
            sys.platform = old_platform

    def test_os_user_name(self):
        print(os_user_name())
        assert os_user_name()

    def test_parse_dotenv_dollar_char_does_not_cutoff_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write('declaredVar = DeclaredValue\n')
            fp.write('replacedVar = beforeTheDollar$declaredVar\n')
            fp.write('uncutVar=beforeTheDollar$afterTheDollar\n')
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'replacedVar' in loaded
            assert 'uncutVar' in loaded
            late_env_var_resolver(loaded, loaded, late_resolved)
            assert loaded['replacedVar'] == "beforeTheDollarDeclaredValue"
            assert loaded['uncutVar'] == "beforeTheDollar$afterTheDollar"

    def test_parse_dotenv_double_quoted_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write('var_nam="var val"')
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == "var val"

    def test_parse_dotenv_double_quote_in_single_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("""var_nam='"var val"'""")
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == '"var val"'

    def test_parse_dotenv_exclude_vars_dict_arg(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("exc_var0=var val\nvar_nam=var val\nexc_var1='excluded var val'")
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {}, exclude_vars={'exc_var0': "not overwritten value", 'exc_var1': ""})

            assert 'exc_var0' not in loaded
            assert 'exc_var1' not in loaded
            assert 'var_nam' in loaded

    def test_parse_dotenv_exclude_vars_tuple_arg(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("exc_var0=var val\nvar_nam=var val\nexc_var1='excluded var val'")
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {}, exclude_vars=('exc_var0', 'exc_var1'))

            assert 'exc_var0' not in loaded
            assert 'exc_var1' not in loaded
            assert 'var_nam' in loaded

    def test_parse_dotenv_error_space_prefixed_var_name(self, recwarn):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write(' var_nam="var val"')
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' not in loaded
            assert len(recwarn) == 1
            assert f"doesn't match {DOTENV_FILENAME} format" in str(recwarn[0].message)

    def test_parse_dotenv_literal_dict_with_list(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            var_val = "{'key': {'sub-key': ['list-item', 'list-item with = char', ]}}"
            fp.write("var_nam=" + var_val)
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == var_val

    def test_parse_dotenv_literal_dict_with_list_quoted(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            var_val = "{'key': {'sub-key': ['list-item', 'list-item with = char']}}"
            fp.write('var_nam="' + var_val + '"')
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == var_val

    def test_parse_dotenv_multi_line_var_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            var_val = "{'key': {'sub-key':\\\n    ['list-item',\\\n     'list-item with = char', ]}}"
            fp.write("var_nam=" + var_val)
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == var_val.replace('\\\n', "")

    def test_parse_dotenv_single_in_double_quoted_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write('''var_nam="'var val'"''')
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == "'var val'"

    def test_parse_dotenv_single_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam='var val'")
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == "var val"

    def test_parse_dotenv_start_parent_first_in_chain(self, os_env_test_env):
        assert DOTENV_VAR_NAME not in os.environ
        file_path = os.path.join(os_env_test_env, DOTENV_DIR_NAME, DOTENV_FILENAME)

        loaded = parse_dotenv(file_path, {})

        assert DOTENV_VAR_NAME in loaded
        assert loaded[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '1'

    def test_parse_dotenv_space_surrounded_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam   =   var val   ")
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == "var val"

    def test_parse_dotenv_unquoted_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam=var val")
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == "var val"

    def test_parse_dotenv_var_escaped_double_quote(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write('var_nam="escaped\\"val"')
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded
            late_env_var_resolver(loaded, loaded, late_resolved)
            assert loaded['var_nam'] == 'escaped"val'

    def test_parse_dotenv_var_empty_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam=")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded
            late_env_var_resolver(loaded, loaded, late_resolved)
            assert loaded['var_nam'] == ""

    def test_parse_dotenv_var_expands_variables_found_in_values(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("env_var=var val\nvar_nam=$env_var")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded
            late_env_var_resolver(loaded, loaded, late_resolved)
            assert loaded['var_nam'] == "var val"
            assert 'env_var' in loaded
            assert loaded['env_var'] == "var val"

    def test_parse_dotenv_var_expands_variable_wrapped_in_brackets(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("env_var=var val\n\n\nvar_nam=${env_var} tst")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded
            late_env_var_resolver(loaded, loaded, late_resolved)
            assert loaded['var_nam'] == "var val tst"
            assert 'env_var' in loaded
            assert loaded['env_var'] == "var val"

    def test_parse_dotenv_var_expands_not_an_undefined_variable_to_empty_string(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam=$env_var")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'env_var' not in loaded
            assert 'var_nam' in loaded
            late_env_var_resolver(loaded, loaded, late_resolved)
            assert loaded['var_nam'] == "$env_var"

    def test_parse_dotenv_var_expands_in_double_quoted_values(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("env_var=tst\nvar_nam=\"var val $env_var\"")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded
            late_env_var_resolver(loaded, loaded, late_resolved)
            assert loaded['var_nam'] == "var val tst"

    def test_parse_dotenv_var_export_keyword(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("export var_nam=var val")
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == "var val"

    def test_parse_dotenv_var_not_expands_in_single_quoted_values(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam='var val $env_var'")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded
            late_env_var_resolver(loaded, loaded, late_resolved)
            assert loaded['var_nam'] == "var val $env_var"

    def test_parse_dotenv_var_not_expands_escaped_variables(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam=var val \\$env_var \\${env_var}")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded
            late_env_var_resolver(loaded, loaded, late_resolved)
            assert loaded['var_nam'] == "var val $env_var ${env_var}"

    def test_project_main_file(self, tmp_path):
        assert project_main_file("not_existing_xy.tst") == ""

        ae_system_main_file = norm_path(os.path.join("ae", "system" + PY_EXT))
        assert project_main_file("ae.system") == ae_system_main_file
        assert project_main_file("ae.system", norm_path("")) == ae_system_main_file

        local_project_dir = os.path.join(str(tmp_path), "ae_system")
        local_main_file = norm_path(os.path.join(local_project_dir, "main.py"))

        write_file(local_main_file, "# main file content", make_dirs=True)
        assert project_main_file("ae.system") == ae_system_main_file
        assert project_main_file("ae.system", norm_path("")) == ae_system_main_file
        assert project_main_file("ae.system", local_project_dir) == local_main_file
        assert project_main_file("ae.system", norm_path(local_project_dir)) == local_main_file

    def test_sys_env_dict(self):
        assert sys_env_dict().get('python ver')
        assert sys_env_dict().get('cwd')
        assert sys_env_dict().get('frozen') is False

        assert sys_env_dict().get('bundle_dir') is None
        sys.frozen = True
        assert sys_env_dict().get('bundle_dir')
        # noinspection PyUnresolvedReferences
        del sys.__dict__['frozen']      # sys.__dict__.pop('frozen')
        assert sys_env_dict().get('bundle_dir') is None

    def test_sys_env_text(self):
        assert isinstance(sys_env_text(), str)
        assert 'python ver' in sys_env_text()
        ret = sys_env_text(extra_sys_env_dict=dict(test_add='TstAdd'))
        assert 'test_add' in ret
        assert 'TstAdd' in ret


class TestModuleHelpers:
    def test_module_attr_callable_with_args(self):
        namespace = TESTS_FOLDER
        mod_name = 'test_module_name'
        att_name = 'test_module_func'
        # noinspection PyUnnecessaryCast
        module_file = cast(str, os.path.join(namespace, mod_name + PY_EXT))
        try:
            write_file(module_file, f"def {att_name}(*args, **kwargs):\n    return args, kwargs\n")
            args = (1, '2')
            kwargs = dict(kwarg1=1, kwarg2='2')

            ret = module_attr(namespace + '.' + mod_name, att_name)
            assert ret
            assert callable(type(ret))

            call_ret = ret(*args, **kwargs)
            assert call_ret
            assert call_ret[0] == args
            assert call_ret[1] == kwargs

        finally:
            if os.path.exists(module_file):
                os.remove(module_file)

        # test already imported module
        # noinspection PyUnreachableCode
        callee = module_attr('textwrap', 'indent')
        assert callable(callee)
        assert callee is textwrap.indent

    def test_module_attr_callable_wrong_args(self):
        namespace = TESTS_FOLDER
        mod_name = 'test_module_name'
        att_name = 'test_module_func'
        # noinspection PyUnnecessaryCast
        module_file = cast(str, os.path.join(namespace, mod_name + PY_EXT))
        try:
            write_file(module_file, f"def {att_name}(arg1, args2, kwarg1='default'):\n    return arg1, arg2, kwarg1\n")

            callee = module_attr(namespace + '.' + mod_name, att_name)
            assert callable(callee)

            args = (1, '2')
            kwargs = dict(kwarg1=1, kwarg2='2')
            with pytest.raises(TypeError):
                callee(*args, **kwargs)

        finally:
            if os.path.exists(module_file):
                os.remove(module_file)

    def test_module_attr_imported(self):
        """ test with module w/ and w/o namespace. """
        assert isinstance(module_attr('os', 'path'), ModuleType)
        assert module_attr('textwrap', 'dedent') is textwrap.dedent
        assert callable(module_attr('ae.system', 'module_attr'))
        assert callable(module_attr('ae.base', 'norm_name'))

    def test_module_attr_module_ref(self, monkeypatch, tmp_path):
        namespace = str(tmp_path)
        mod_name = 'test_module_name'
        attr_nam = 'module_var'
        attr_val = 369
        # noinspection PyUnnecessaryCast
        module_file = cast(str, os.path.join(namespace, mod_name + PY_EXT))

        write_file(module_file, f"# unregistered tst module\n{attr_nam} = {attr_val}")

        assert module_attr(namespace + '.' + mod_name, attr_nam) == attr_val

        monkeypatch.chdir(namespace)

        assert module_attr(mod_name, attr_nam) == attr_val

    def test_module_attr_not_exists_attr(self, monkeypatch, tmp_path):
        """ first test with a non-existing module, second test with a non-existing function. """
        namespace = str(tmp_path)
        mod_name = 'test_module_name'
        att_name = 'test_module_func'
        # noinspection PyUnnecessaryCast
        module_file = cast(str, os.path.join(namespace, mod_name + PY_EXT))
        write_file(module_file, f"""def {att_name}(*args, **kwargs):\n    pass\n""")

        assert module_attr(namespace + '.' + mod_name, "not_existing_func_or_attr") is UNSET

        assert callable(module_attr(namespace + '.' + mod_name, att_name))

        monkeypatch.chdir(namespace)

        assert module_attr(mod_name, "") is UNSET
        assert module_attr(mod_name, "not-existing-attr-name") is UNSET

    def test_module_attr_not_exists_module(self):
        assert module_attr('non_existing_test_module_name', 'non_existing_test_module_func') is None

    def test_module_file_path(self):
        assert module_file_path() == __file__
        assert module_file_path(lambda: 0) == __file__

    def test_module_find_builtins(self):
        path_or_err = module_find('textwrap')
        assert isinstance(path_or_err, str)

        path_or_err = module_find('os.path')
        assert isinstance(path_or_err, str)

        path_or_err = module_find('os')
        assert isinstance(path_or_err, str)

    def test_module_find_local_module(self, monkeypatch, tmp_path):
        module = "tst_mod_nam"
        mod_file = os.path.join(str(tmp_path), module + PY_EXT)
        write_file(mod_file, f"# module_find test module\nsome_var = 'some_var_val'")

        assert isinstance(module_find(module), list)    # not found because neither under sys.path nor in sys.modules

        monkeypatch.syspath_prepend(str(tmp_path))

        mod_path = module_find(module)

        assert isinstance(mod_path, str)

    def test_module_load_builtins(self):
        assert isinstance(module_load('textwrap'), ModuleType)
        assert isinstance(module_load('os.path'), ModuleType)
        assert isinstance(module_load('os'), ModuleType)

    def test_module_load_local_module(self, monkeypatch, tmp_path):
        module = "mod_2_tst"
        mod_file = os.path.join(str(tmp_path), module + PY_EXT)
        write_file(mod_file, "mod_var = 'mod_var_val'")

        mod_ref = module_load(module, path=os_path_dirname(mod_file))

        assert isinstance(mod_ref, list)    # load error
        assert isinstance(mod_ref[0], str)

        mod_ref = module_load(str(tmp_path) + '.' + module)

        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

        mod_ref = module_load(module)

        assert isinstance(mod_ref, list)    # load error
        assert isinstance(mod_ref[0], str)

        monkeypatch.chdir(str(tmp_path))

        mod_ref = module_load(module, path=module + PY_EXT)

        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

        mod_ref = module_load(module)

        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

    def test_module_load_local_package(self, monkeypatch, tmp_path):
        namespace = "y_xx"
        portion = "por_2_tst"

        pkg_path = os.path.join(str(tmp_path), namespace, portion)
        pkg_file = os.path.join(pkg_path, PY_INIT)
        write_file(pkg_file, "pkg_var = 'pkg_var_val'", make_dirs=True)

        mod_ref = module_load(portion, path=pkg_path)

        assert isinstance(mod_ref, list)
        assert isinstance(mod_ref[0], str)

        mod_ref = module_load(namespace + '.' + portion, path=os_path_dirname(pkg_path))

        assert isinstance(mod_ref, list)
        assert isinstance(mod_ref[0], str)

        mod_ref = module_load(str(tmp_path) + '.' + namespace + '.' + portion, path=pkg_path)

        assert isinstance(mod_ref, list)
        assert isinstance(mod_ref[0], str)

        mod_ref = module_load(str(tmp_path) + '.' + namespace + '.' + portion)

        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

        monkeypatch.chdir(str(tmp_path))

        mod_ref = module_load(namespace + '.' + portion)

        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

        mod_ref = module_load(namespace + '.' + portion, path=os.path.relpath(pkg_file, str(tmp_path)))

        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

    def test_module_load_not_exists(self):
        assert (err_or_mod := module_load('not_existing_import_name'))
        assert isinstance(err_or_mod, list)


class TestStackHelpers:
    def test_full_stack_trace(self):
        local_var = 'test_local_variable_value'
        try:
            raise ValueError('tst val err')
        except ValueError as ex:
            assert full_stack_trace(ex)
            assert 'ValueError' in full_stack_trace(ex)
            assert 'tst val err' in full_stack_trace(ex)
            assert 'test_full_stack_trace' in full_stack_trace(ex)
            assert 'TestStackHelpers' in full_stack_trace(ex)
            assert 'local_var' in full_stack_trace(ex)
            assert local_var in full_stack_trace(ex)

    def test_full_stack_trace_without_locals(self):
        local_var = 'test_local_variable_value'
        try:
            raise SyntaxError('tst error xyz')
        except SyntaxError as ex:
            assert full_stack_trace(ex)
            assert 'SyntaxError' in full_stack_trace(ex, frames_with_locals=0)
            assert 'tst error xyz' in full_stack_trace(ex, frames_with_locals=0)
            assert 'test_full_stack_trace_without_locals' in full_stack_trace(ex, frames_with_locals=0)

            assert 'TestStackHelpers' not in full_stack_trace(ex, frames_with_locals=0)
            assert 'local_var' not in full_stack_trace(ex, frames_with_locals=0)
            assert local_var not in full_stack_trace(ex, frames_with_locals=0)

    def test_stack_frames(self):
        for frame in stack_frames():
            assert frame
            assert getattr(frame, 'f_globals')
            # if pytest runs from terminal, then f_locals is missing in the highest frame:
            # assert getattr(frame, 'f_locals')

    def test_stack_var_module(self):
        assert module_test_var
        assert stack_var('module_test_var', depth=-1) == 'module_test_var_val'
        assert stack_var('module_test_var', depth=0) == 'module_test_var_val'
        assert stack_var('module_test_var', scope='globals', depth=0) == 'module_test_var_val'
        assert stack_var('module_test_var', 'ae.system', depth=0) == 'module_test_var_val'

        assert stack_var('module_test_var') is UNSET      # depth==1 (def)
        assert stack_var('module_test_var', depth=2) is UNSET
        assert stack_var('module_test_var', scope='locals', depth=0) is UNSET
        assert stack_var('module_test_var', scope='locals') is UNSET
        assert stack_var('module_test_var', 'test_system') is UNSET
        assert stack_var('module_test_var', 'ae.system', 'test_system') is UNSET

    def test_stack_var_func(self):
        _func_var = 'func_var_val'

        assert stack_var('_func_var', 'ae.system', scope='locals', depth=0) == 'func_var_val'
        assert stack_var('_func_var', depth=0) == 'func_var_val'
        assert stack_var('_func_var', scope='locals', depth=0) == 'func_var_val'

        # assert stack_var('_func_var', scope='locals', depth=1) is UNSET
        assert stack_var('_func_var') is UNSET
        assert stack_var('_func_var', scope='globals', depth=0) is UNSET
        assert stack_var('_func_var', 'test_system', scope='locals') is UNSET
        assert stack_var('_func_var', 'ae.system', 'test_system', scope='locals') is UNSET
        assert stack_var('_func_var', scope='locals', depth=3) is UNSET

    def test_stack_var_inner_func(self):
        def _inner_func():
            _inner_var = 'inner_var_val'
            assert stack_var('_inner_var', depth=-1) == 'inner_var_val'
            assert stack_var('_inner_var', depth=0) == 'inner_var_val'
            assert stack_var('_inner_var', scope='locals', depth=0) == 'inner_var_val'
            assert stack_var('_inner_var', 'ae.system', scope='locals', depth=0) == 'inner_var_val'
            assert stack_var('_inner_var', 'ae.system', 'xxx yyy', scope='locals', depth=0) == 'inner_var_val'

            assert stack_var('_inner_var') is UNSET     # depth==1 (def)
            assert stack_var('_inner_var', depth=2) is UNSET
            assert stack_var('_inner_var', scope='globals', depth=0) is UNSET
            assert stack_var('_inner_var', 'test_system', scope='locals', depth=0) is UNSET

            assert stack_var('_outer_var') == 'outer_var_val'
            assert stack_var('_outer_var', depth=0) == 'outer_var_val'
            assert stack_var('_outer_var', 'ae.system', scope='locals') == 'outer_var_val'
            assert stack_var('_outer_var', scope='locals') == 'outer_var_val'
            assert stack_var('_outer_var', scope='locals', depth=0) == 'outer_var_val'

            assert stack_var('_outer_var', scope='locals', depth=2) is UNSET
            assert stack_var('_outer_var', 'test_system', scope='locals') is UNSET
            assert stack_var('_outer_var', 'ae.system', 'test_system', scope='locals') is UNSET

            assert stack_var('module_test_var') == 'module_test_var_val'
            assert stack_var('module_test_var', scope='globals') == 'module_test_var_val'

            assert stack_var('module_test_var', depth=2) is UNSET
            assert stack_var('module_test_var', scope='locals') is UNSET
            assert stack_var('module_test_var', 'test_system') is UNSET
            assert stack_var('module_test_var', 'ae.system', 'test_system') is UNSET

        _outer_var = 'outer_var_val'
        _inner_func()

        assert stack_var('_outer_var', depth=0) == 'outer_var_val'
        assert stack_var('_outer_var', 'ae.system', scope='locals', depth=0) == 'outer_var_val'
        assert stack_var('_outer_var', scope='locals', depth=0) == 'outer_var_val'

        assert stack_var('_outer_var') is UNSET
        assert stack_var('_outer_var', scope='locals') is UNSET
        assert stack_var('_outer_var', scope='locals', depth=2) is UNSET
        assert stack_var('_outer_var', 'test_system') is UNSET

        assert stack_var('module_test_var', depth=0) == 'module_test_var_val'
        assert stack_var('module_test_var', depth=0, scope='globals') == 'module_test_var_val'

        assert stack_var('module_test_var') is UNSET
        assert stack_var('module_test_var', depth=2) is UNSET
        assert stack_var('module_test_var', depth=3) is UNSET
        assert stack_var('module_test_var', scope='locals', depth=0) is UNSET
        assert stack_var('module_test_var', 'test_system') is UNSET
        assert stack_var('module_test_var', 'ae.system', 'test_system') is UNSET

    def test_stack_vars(self):
        local_var = "loc_var_val"
        glo, loc, deep = stack_vars(min_depth=0, max_depth=1)
        assert deep == 1
        assert 'local_var' in loc
        assert loc['local_var'] == local_var

        glo, loc, deep = stack_vars(max_depth=3)
        assert deep == 3

        glo, loc, deep = stack_vars(min_depth=0, find_name='module_test_var')    # min_depth needed for this stack frame
        assert glo.get('module_test_var') == 'module_test_var_val'

        glo, loc, deep = stack_vars(find_name='module_test_var')                 # min_depth default == 1
        assert glo.get('module_test_var') is None

        glo, loc, deep = stack_vars(min_depth=2, find_name='module_test_var')    # min_depth needed for this stack frame
        assert glo.get('module_test_var') is None


class TestPyMo:
    def test_from_name(self):
        assert PyMo.from_name("") is not None
        # noinspection PyTypeChecker
        assert PyMo.from_name(None).import_name == 'import.name.error'
        assert PyMo.from_name("").import_name == 'import.name.error'
        assert PyMo.from_name("", namespace_name=".").import_name == 'import.name.error'
        assert PyMo.from_name("", namespace_name="tst").import_name == 'import.name.error'
        assert PyMo.from_name("", namespace_name="tst.name").import_name == 'import.name.error'

        assert (_mod := PyMo.from_name("imp.tst.name")) is not None
        assert _mod.import_name == "imp.tst.name"
        assert _mod.project_root_path == norm_path("imp_tst_name")

        assert (_mod := PyMo.from_name("imp.tst.name", namespace_name="imp")) is not None
        assert _mod.import_name == "imp.tst.name"
        assert _mod.project_root_path == norm_path("imp_tst_name")

        assert (_mod := PyMo.from_name("imp.tst.name", namespace_name="imp.tst")) is not None
        assert _mod.import_name == "imp.tst.name"
        assert _mod.project_root_path == norm_path("imp_tst_name")

        assert (_mod := PyMo.from_name("pip-tst-name")) is not None
        assert _mod.import_name == "pip_tst_name"
        assert _mod.project_root_path == norm_path("pip_tst_name")

        assert (_mod := PyMo.from_name("pip-tst-name", namespace_name="pip")) is not None
        assert _mod.import_name == "pip.tst_name"
        assert _mod.project_root_path == norm_path("pip_tst_name")

        assert (_mod := PyMo.from_name("pip-tst-name", namespace_name="pip.tst")) is not None
        assert _mod.import_name == "pip.tst.name"
        assert _mod.project_root_path == norm_path("pip_tst_name")

        assert (_mod := PyMo.from_name("pkg_tst_name")) is not None
        assert _mod.import_name == "pkg_tst_name"
        assert _mod.project_root_path == norm_path("pkg_tst_name")

        assert (_mod := PyMo.from_name("pkg_tst_name", namespace_name="pkg")) is not None
        assert _mod.import_name == "pkg.tst_name"
        assert _mod.project_root_path == norm_path("pkg_tst_name")

        assert (_mod := PyMo.from_name("pkg_tst_name", namespace_name="pkg.tst")) is not None
        assert _mod.import_name == "pkg.tst.name"
        assert _mod.project_root_path == norm_path("pkg_tst_name")

    @skip_gitlab_ci
    def test_from_path_local_src_packages(self):
        parent_dir = norm_path(f"~/{DEF_PROJECT_PARENT_FOLDER}")
        if os_path_isdir(_path := f"{parent_dir}/ae_kivy"):
            assert (_mod := PyMo.from_path(_path))  # w/o namespace_name argument!
            assert _mod.error_message == ""
            assert _mod.import_name == 'ae.kivy'
            assert isinstance(_mod.imported_module, ModuleType)
            assert isinstance(_mod.loaded_module, ModuleType)
            assert hasattr(_mod.loaded_module, '__path__')
            assert _mod.module_file_path == f"{parent_dir}/ae_kivy/ae/kivy{PY_EXT}"
            assert _mod.namespace_name == "ae"
            assert _mod.name_parts == ["ae", "kivy"]
            assert _mod.package_file_path == f"{parent_dir}/ae_kivy/ae/kivy/{PY_INIT}"
            assert _mod.package_name == "ae_kivy"
            assert _mod.pip_name == "ae-kivy"
            assert _mod.portion_name == "kivy"
            assert _mod.project_name == "ae_kivy"
            assert _mod.project_root_path == _path

        if os_path_isdir(_path := f"{parent_dir}/ae_kivy"):
            assert (_mod := PyMo.from_path(_path, namespace_name='ae'))
            assert _mod.error_message == ""
            assert _mod.import_name == 'ae.kivy'
            assert isinstance(_mod.imported_module, ModuleType)
            assert isinstance(_mod.loaded_module, ModuleType)
            assert hasattr(_mod.loaded_module, '__path__')
            assert _mod.module_file_path == f"{parent_dir}/ae_kivy/ae/kivy{PY_EXT}"
            assert _mod.namespace_name == "ae"
            assert _mod.name_parts == ["ae", "kivy"]
            assert _mod.package_file_path == f"{parent_dir}/ae_kivy/ae/kivy/{PY_INIT}"
            assert _mod.package_name == "ae_kivy"
            assert _mod.pip_name == "ae-kivy"
            assert _mod.portion_name == "kivy"
            assert _mod.project_name == "ae_kivy"
            assert _mod.project_root_path == _path

        if os_path_isdir(_path := f"{parent_dir}/ae_kivy_glsl"):
            assert (_mod := PyMo.from_path(_path))  # w/o namespace_name arg
            assert _mod.error_message == ""
            assert _mod.import_name == 'ae.kivy_glsl'
            assert _mod.module_file_path == f"{parent_dir}/ae_kivy_glsl/ae/kivy_glsl{PY_EXT}"
            assert _mod.namespace_name == 'ae'
            assert _mod.name_parts == ['ae', 'kivy_glsl']
            assert _mod.package_file_path == f"{parent_dir}/ae_kivy_glsl/ae/kivy_glsl/{PY_INIT}"
            assert _mod.portion_name == 'kivy_glsl'
            assert _mod.project_root_path == _path

        if os_path_isdir(_path := f"{parent_dir}/ae_kivy_glsl"):
            assert (_mod := PyMo.from_path(_path, namespace_name='ae'))
            assert _mod.error_message == ""
            assert _mod.import_name == 'ae.kivy_glsl'
            assert _mod.module_file_path == f"{parent_dir}/ae_kivy_glsl/ae/kivy_glsl{PY_EXT}"
            assert _mod.namespace_name == 'ae'
            assert _mod.name_parts == ['ae', 'kivy_glsl']
            assert _mod.package_file_path == f"{parent_dir}/ae_kivy_glsl/ae/kivy_glsl/{PY_INIT}"
            assert _mod.portion_name == 'kivy_glsl'
            assert _mod.project_root_path == _path

        if os_path_isdir(_path := f"{parent_dir}/glsl_tester"):
            assert (_mod := PyMo.from_path(_path))
            assert _mod.error_message == ""
            assert _mod.import_name == 'glsl_tester'
            assert _mod.module_file_path == f"{parent_dir}/glsl_tester/glsl_tester{PY_EXT}"
            assert _mod.namespace_name == ''
            assert _mod.name_parts == ["glsl_tester"]
            assert _mod.package_name == 'glsl_tester'
            assert _mod.project_root_path == _path

        if os_path_isdir(_path := f"{parent_dir}/oaio_server"):
            assert (_mod := PyMo.from_path(_path))
            assert _mod.error_message == ""
            assert _mod.import_name == 'oaio_server'
            assert _mod.namespace_name == ''
            assert _mod.name_parts == ["oaio_server"]
            assert _mod.package_name == "oaio_server"
            assert _mod.project_root_path == _path

        if os_path_isdir(_path := f"{parent_dir}/kairos"):
            assert (_mod := PyMo.from_path(_path))
            assert _mod.error_message == ""
            assert _mod.import_name == 'kairos'
            assert _mod.namespace_name == ''
            assert _mod.name_parts == ["kairos"]
            assert _mod.project_root_path == _path

    def test_from_path_not_existing(self):
        assert PyMo.from_path("") is not None
        assert PyMo.from_path("").import_name == 'ae.system'
        assert PyMo.from_path("", namespace_name=".") is not None
        assert PyMo.from_path("", namespace_name="namespacename") is not None
        assert PyMo.from_path("", namespace_name="namespace.name") is not None
        assert PyMo.from_path("", namespace_name="namespace-name") is not None
        assert PyMo.from_path("", namespace_name="namespace_name") is not None

        assert (_mod := PyMo.from_path("not_existing_project_dir")) is not None
        assert _mod.import_name == "not_existing_project_dir"

        assert (_mod := PyMo.from_path("not_existing_project_dir", namespace_name="not.existing")) is not None
        assert _mod.import_name == "not.existing.project_dir"

        assert PyMo.from_path("~/_not_existing") is not None

    def test_pymo_class_and_instance(self):
        assert PyMo("").__class__ is PyMo
        assert PyMo("")
        assert PyMo("xy_abc")
        assert PyMo("a.b.c")

    def test_imported_module_ae_base(self):
        mod_ref = PyMo('ae.base').imported_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'TESTS_FOLDER') == TESTS_FOLDER

    def test_imported_module_built_ins(self):
        assert isinstance(PyMo('os').imported_module, ModuleType)
        assert isinstance(PyMo('os.path').imported_module, ModuleType)
        assert isinstance(PyMo('textwrap').imported_module, ModuleType)

    def test_imported_module_local_module(self, monkeypatch, tmp_path):
        module = "mod_2_tst"
        # noinspection PyUnnecessaryCast
        mod_file = cast(str, os.path.join(str(tmp_path), module + PY_EXT))
        write_file(mod_file, "mod_var = 'mod_var_val'")

        assert PyMo(module).imported_module is None

        assert PyMo(module, project_path=str(tmp_path)).imported_module is None

        assert PyMo(os_path_basename(str(tmp_path)) + '.' + module).imported_module is None

        monkeypatch.chdir(str(tmp_path))

        assert PyMo(module, project_path=module + PY_EXT).imported_module is None

        assert PyMo(module).imported_module is None

        monkeypatch.syspath_prepend(str(tmp_path))

        mod_ref = PyMo(module, project_path=mod_file).imported_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

        monkeypatch.syspath_prepend(os_path_dirname(str(tmp_path)))

        mod_ref = PyMo(os_path_basename(str(tmp_path)) + '.' + module).imported_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

    def test_imported_module_local_package(self, monkeypatch, tmp_path):
        namespace = "z_y"
        portion = "por_2_tst"
        pkg_root = os.path.join(str(tmp_path), namespace)
        pkg_path = os.path.join(pkg_root, portion)
        pkg_file = os.path.join(pkg_path, PY_INIT)
        write_file(pkg_file, "pkg_var = 'pkg_var_val'", make_dirs=True)

        assert PyMo(namespace + '.' + portion).imported_module is None

        assert PyMo(portion).loaded_module is None

        assert PyMo(portion, project_path=pkg_root).imported_module is None

        assert PyMo(portion, project_path=pkg_file).imported_module is None

        assert PyMo(namespace + '.' + portion, project_path=os_path_dirname(pkg_root)).imported_module is None

        assert PyMo(str(tmp_path) + '.' + namespace + '.' + portion, project_path=pkg_root).imported_module is None

        assert PyMo(str(tmp_path) + '.' + namespace + '.' + portion).imported_module is None

        monkeypatch.chdir(str(tmp_path))

        assert PyMo(namespace + '.' + portion).imported_module is None

        assert PyMo(namespace + '.' + portion,
                    project_path=os.path.relpath(pkg_file, str(tmp_path))).imported_module is None

        monkeypatch.syspath_prepend(str(tmp_path))

        mod_ref = PyMo(namespace + '.' + portion).imported_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

        mod_ref = PyMo(namespace + '.' + portion, project_path="any_path").imported_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

        monkeypatch.syspath_prepend(os_path_dirname(str(tmp_path)))

        mod_ref = PyMo(namespace + '.' + portion).imported_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

        mod_ref = PyMo(namespace + '.' + portion, project_path=os.path.relpath(pkg_file, str(tmp_path))).imported_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

    def test_imported_module_not_exists(self):
        assert PyMo('not_existing_import_name').imported_module is None

    def test_loaded_module_ae_system(self):
        mod_ref = PyMo('ae.system').loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'DOTENV_FILENAME') == DOTENV_FILENAME

    def test_loaded_module_built_ins(self):
        assert isinstance(PyMo('os').loaded_module, ModuleType)
        assert isinstance(PyMo('textwrap').loaded_module, ModuleType)

    def test_loaded_module_local_module(self, monkeypatch, tmp_path):
        module = "mod_2_tst"
        # noinspection PyUnnecessaryCast
        mod_file = cast(str, os.path.join(str(tmp_path), module + PY_EXT))
        write_file(mod_file, "mod_var = 'mod_var_val'")

        assert PyMo(module + PY_EXT).loaded_module is None

        mod_ref = PyMo(module).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

        mod_ref = PyMo(module, project_path=os_path_dirname(mod_file)).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

        mod_ref = PyMo(os_path_basename(str(tmp_path)) + '.' + module,
                       project_path=os_path_dirname(str(tmp_path))).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

        mod_ref = PyMo(str(tmp_path) + '.' + module).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

        monkeypatch.chdir(str(tmp_path))

        mod_ref = PyMo(module, project_path=module + PY_EXT).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

        mod_ref = PyMo(module).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

    def test_loaded_module_local_package(self, monkeypatch, tmp_path):
        namespace = "n_s"
        portion = "por_2_tst"
        pkg_root = os.path.join(str(tmp_path), namespace)
        pkg_path = os.path.join(pkg_root, portion)
        pkg_file = os.path.join(pkg_path, PY_INIT)
        write_file(pkg_file, "pkg_var = 'pkg_var_val'", make_dirs=True)

        assert PyMo(namespace + '.' + portion).loaded_module is None

        assert PyMo(portion).loaded_module is None

        mod_ref = PyMo(portion, project_path=pkg_root).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

        mod_ref = PyMo(namespace + '.' + portion, project_path=os_path_dirname(pkg_root)).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

        mod_ref = PyMo(str(tmp_path) + '.' + namespace + '.' + portion, project_path=pkg_root).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

        mod_ref = PyMo(str(tmp_path) + '.' + namespace + '.' + portion).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

        monkeypatch.chdir(str(tmp_path))

        mod_ref = PyMo(namespace + '.' + portion).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

        mod_ref = PyMo(namespace + '.' + portion, project_path=os.path.relpath(pkg_file, str(tmp_path))).loaded_module
        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

    def test_loaded_module_not_exists(self):
        assert PyMo('not_existing_import_name').loaded_module is None

    def test_module_file_path(self):
        mod = PyMo("tst_nam")
        assert mod.module_file_path == f"tst_nam{PY_EXT}"

        mod = PyMo("tst_nam", project_path="prj_path")
        assert mod.module_file_path == os_path_join("prj_path", "tst_nam" + PY_EXT)

        mod = PyMo("tst.nam", project_path="prj_path")
        assert mod.module_file_path == os_path_join("prj_path", "tst", "nam" + PY_EXT)

    def test_namespace_guess_module_portion(self, tmp_path):
        namespace = 'z_y'
        portion_name = 'portion_name'
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        project_name = namespace + "_" + portion_name
        project_path = os_path_join(parent_dir, project_name)
        namespace_dir = os_path_join(project_path, namespace)
        main_file = os_path_join(namespace_dir, portion_name + PY_EXT)
        write_file(main_file, "# main file of module portion", make_dirs=True)

        assert PyMo.from_path(project_path).namespace_name == namespace

    def test_namespace_guess_package_portion(self, tmp_path):
        namespace = 'x_y'
        portion_name = 'portion_name'
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        project_name = namespace + "_" + portion_name
        project_path = os_path_join(parent_dir, project_name)
        namespace_dir = os_path_join(project_path, namespace)
        portion_dir = os_path_join(namespace_dir, portion_name)
        main_file = os_path_join(portion_dir, PY_INIT)
        write_file(main_file, "# main file of package portion", make_dirs=True)

        assert PyMo.from_path(project_path).namespace_name == namespace

    def test_namespace_guess_project_at_cwd(self):
        assert PyMo.from_path("").namespace_name == 'ae'
        assert PyMo.from_path(os.getcwd()).namespace_name == 'ae'

    def test_namespace_guess_root(self, tmp_path):
        namespace = 'x_z'
        parent_dir = os_path_join(tmp_path, DEF_PROJECT_PARENT_FOLDER)
        project_path = os_path_join(parent_dir, namespace + "_" + namespace)
        main_file = os_path_join(project_path, namespace + PY_EXT)
        write_file(main_file, "# main file of non-namespace module", make_dirs=True)

        assert not PyMo.from_path(project_path).namespace_name

        os.remove(main_file)

        main_file = os_path_join(project_path, 'main' + PY_EXT)
        write_file(main_file, "# main file of non-namespace project")

        assert PyMo.from_path(project_path).namespace_name == ""

        os.remove(main_file)

        main_file = os_path_join(project_path, PY_INIT)
        write_file(main_file, "# main file of non-namespace package")

        assert PyMo.from_path(project_path).namespace_name == ""

        os.remove(main_file)

        por_dir = os_path_join(project_path, namespace)
        main_file = os_path_join(por_dir, namespace + PY_EXT)
        write_file(main_file, "# main file of namespace root module", make_dirs=True)

        assert PyMo.from_path(project_path).namespace_name == namespace

        os.remove(main_file)

        main_file = os_path_join(por_dir, 'main' + PY_EXT)
        write_file(main_file, "# main file of namespace root main")

        assert PyMo.from_path(project_path).namespace_name == namespace

        os.remove(main_file)

        por_dir = os_path_join(por_dir, namespace)   # == os_path_join(project_path, namespace, namespace)
        main_file = os_path_join(por_dir, PY_INIT)
        write_file(main_file, "# main file of namespace root package", make_dirs=True)

        assert PyMo.from_path(project_path).namespace_name == namespace

    def test_namespace_guess_sub_module(self):
        assert PyMo.from_path(TESTS_FOLDER) is not None
        assert PyMo.from_path(TESTS_FOLDER).namespace_name == ""

    def test_namespace_guess_with_underscore(self, tmp_path):
        namespace = 'n_x'
        parent_dir = os_path_join(tmp_path, DEF_PROJECT_PARENT_FOLDER)
        project_path = os_path_join(parent_dir, namespace + "_" + namespace)
        por_dir = os_path_join(project_path, namespace, namespace)
        write_file(os_path_join(por_dir, PY_INIT), "# main file of non-namespace module", make_dirs=True)

        assert PyMo.from_path(project_path).namespace_name == namespace

    def test_package_dir_path(self):
        mod = PyMo("tst_nam")
        assert mod.package_dir_path == "tst_nam"

        mod = PyMo("tst_nam", project_path="prj_path")
        assert mod.package_dir_path == os_path_join("prj_path", "tst_nam")

        mod = PyMo("tst.nam", project_path="prj_path")
        assert mod.package_dir_path == os_path_join("prj_path", "tst", "nam")

    def test_package_file_path(self):
        mod = PyMo("tst_nam")
        assert mod.package_file_path == f"tst_nam/{PY_INIT}"

        mod = PyMo("tst_nam", project_path="prj_path")
        assert mod.package_file_path == os_path_join("prj_path", "tst_nam", PY_INIT)

        mod = PyMo("tst.nam", project_path="prj_path")
        assert mod.package_file_path == os_path_join("prj_path", "tst", "nam", PY_INIT)

    def test_pip_name(self):
        mod = PyMo("tst_nam")
        assert mod.pip_name == "tst-nam"

        mod = PyMo("tst.nam")
        assert mod.pip_name == "tst-nam"

        mod = PyMo('PIL')
        assert mod.pip_name == "pillow"

        mod = PyMo("tst.nam", **{"tst.nam": "Irregular-Name"})
        assert mod.project_name == "Irregular-Name"

    def test_portion_name(self):
        mod = PyMo("tst_nam")
        assert mod.portion_name == "tst_nam"

        mod = PyMo("tst.nam")
        assert mod.portion_name == "nam"

    def test_project_name(self):
        mod = PyMo("tst_nam")
        assert mod.project_name == "tst_nam"

        mod = PyMo('PIL')
        assert mod.project_name == "Pillow"

        mod = PyMo('PIL', **{'PIL': 'PIL'})
        assert mod.project_name == "PIL"

        mod = PyMo('PIL', PIL='PIL')
        assert mod.project_name == "PIL"

        mod = PyMo('namespace.mod', **{"namespace.mod": "Irr-Nam-Mod"})
        assert mod.project_name == "Irr-Nam-Mod"

    def test_pypi_names(self):
        pypi_names = {'tst.pypi.nam': 'Irr-Name', 'PIP': 'New-Pip'}

        mod = PyMo('tst.pypi.nam', **pypi_names)
        assert mod.project_name == pypi_names['tst.pypi.nam']
        assert mod.pip_name == pypi_names['tst.pypi.nam'].lower()

        mod = PyMo('PIP', **pypi_names)
        assert mod.project_name == pypi_names['PIP']
        assert mod.pip_name == pypi_names['PIP'].lower()

    def test_repr(self):
        mod = PyMo("any_name")
        assert repr(mod).startswith("PyMo('any_name'")
