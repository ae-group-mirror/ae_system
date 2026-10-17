""" ae.system unit tests """
import importlib
import os
import sys
import tempfile
import textwrap
import warnings

from configparser import ConfigParser
from types import ModuleType
from unittest.mock import patch, MagicMock

import pytest

from tests.conftest import skip_gitlab_ci

from ae.base import (
    UNSET,
    norm_path, os_path_dirname, os_path_isfile, os_path_join, os_path_relpath, write_file)


import ae.system  # to test and reload/import global module variables (os_device_id) for all supported platforms
# noinspection PyProtectedMember
from ae.system import (
    DOTENV_VAR_IN_VAL_MATCHER,
    app_name_guess, build_config_variable_values, full_stack_trace, instantiate_config_parser,
    late_env_var_resolver, load_dotenvs, load_env_var_defaults,
    module_attr, module_find, module_load, module_file_path, norm_pip_name,
    os_env_venv, os_host_name, os_local_ip, _os_platform, os_user_name,
    parse_dotenv, stack_frames, stack_var, stack_vars, sys_env_dict, sys_env_text, venv_prefix)


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
            file_path = os_path_join(tmp_path, *((DOTENV_DIR_NAME, ) * level))
            os.makedirs(file_path, exist_ok=True)
            if level in DOTENV_FULL_DIRS:
                content = (os.linesep + DOTENV_VAR_NAME + "='" + DOTENV_VAR_VAL + str(level) + "'" +
                           os.linesep + DOTENV_LATE_VAR_PRE + str(level) + '="' + DOTENV_LIT_VALUES[level] + '"' +
                           os.linesep + "RecursiveWithLowerCase = $RecursiveWithLowerCase")
                write_file(os_path_join(file_path, '.env'), content)

        old_env = os.environ
        os.environ = old_env.copy()

        yield tmp_path

        os.environ = old_env


class TestCommonHelpers:
    def test_app_name_guess(self):
        assert app_name_guess()     # app.exe name in pytest returning '_jb_pytest_runner'(PyCharm)/'__main__'(console)
        assert app_name_guess() != 'main'
        assert app_name_guess() == 'unguessable'

    def test_build_config_variable_values_with_spec(self, monkeypatch, tmp_path):
        monkeypatch.chdir(str(tmp_path))
        write_file('buildozer.spec', "[app]\nexisting = tst")
        existing, not_existing = build_config_variable_values(
            ('existing', ""),
            ('not_existing', "default_value")
        )
        assert existing == "tst"
        assert not_existing == "default_value"

    def test_build_config_variable_values_no_spec(self):
        assert not os_path_isfile('buildozer.spec')
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

    def test_norm_pip_name(self):
        assert norm_pip_name('') == ''
        assert norm_pip_name('Abc.DEF-gHi_jkL') == 'abc-def-ghi-jkl'

    def test_os_host_name(self):
        print(os_host_name())
        assert os_host_name()

    def test_os_local_ip(self):
        assert os_local_ip() or os_local_ip() == ""

    def test_os_local_ip_err(self):
        mock_sock = MagicMock()
        mock_sock.getsockname.side_effect = Exception()
        with patch('ae.system.socket.socket', return_value=mock_sock):
            assert os_local_ip() == ""

    def test_os_platform_android1(self, monkeypatch):
        monkeypatch.setenv('ANDROID_ARGUMENT', 'tst')
        os.environ['ANDROID_ARGUMENT'] = 'tst'
        assert _os_platform() == 'android'

    def test_os_platform_android2(self, monkeypatch):
        monkeypatch.setenv('KIVY_BUILD', 'android')
        os.environ['KIVY_BUILD'] = 'android'
        assert _os_platform() == 'android'

    def test_os_platform_cygwin(self):
        with patch('sys.platform', 'cygwin'):
            assert _os_platform() == 'cygwin'

    def test_os_platform_darwin(self):
        with patch('sys.platform', 'darwin'):
            assert _os_platform() == 'darwin'

    def test_os_platform_freebsd(self):
        with patch('sys.platform', 'freebsd'):
            assert _os_platform() == 'freebsd'

    def test_os_platform_ios(self):
        with patch('sys.platform', 'ios'):
            assert _os_platform() == 'ios'

    def test_os_platform_win32(self):
        with patch('sys.platform', 'win32'):
            assert _os_platform() == 'win32'

    def test_os_user_name(self):
        print(os_user_name())
        assert os_user_name()


class TestEnvVars:
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

        with pytest.raises((AttributeError, TypeError)):
            # noinspection PyTypeChecker
            load_env_var_defaults(None, None)   # STRANGE: raising TypeError in Python 3.9.21/local but not in 3.9.23/CI
            # noinspection PyArgumentList
            load_env_var_defaults(None)         # HOTFIX ensuring failure - could not find any changelog notes

        # noinspection PyTypeChecker
        load_env_var_defaults("inv:_ file path", ())  # NO ERROR EXCEPTIONS on these invalid arg values!!!

    def test_load_env_var_defaults_not_loaded(self):
        env_vars = {}

        load_env_var_defaults("/", env_vars)
        assert DOTENV_VAR_NAME not in env_vars

        load_env_var_defaults('.', env_vars)
        assert DOTENV_VAR_NAME not in env_vars

    def test_load_env_var_defaults_not_loaded_in_os_environ(self, os_env_test_env):
        assert DOTENV_VAR_NAME not in os.environ

        load_env_var_defaults("/", os.environ)
        assert DOTENV_VAR_NAME not in os.environ

        load_env_var_defaults('.', os.environ)
        assert DOTENV_VAR_NAME not in os.environ

        load_env_var_defaults(os_path_join(os_env_test_env, *((DOTENV_DIR_NAME,) * 5)), os.environ)
        assert DOTENV_VAR_NAME not in os.environ

        load_env_var_defaults(os_path_join(os_env_test_env, *((DOTENV_DIR_NAME,) * 6)), os.environ)  # too-deep path
        assert DOTENV_VAR_NAME not in os.environ

    def test_load_env_var_defaults_load_start_parent_first_no_chain(self, monkeypatch, os_env_test_env):
        monkeypatch.chdir(os_path_join(os_env_test_env, *((DOTENV_DIR_NAME,) * 4)))

        loaded = load_env_var_defaults("", os.environ)

        assert DOTENV_VAR_NAME in loaded
        assert loaded[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '3'
        assert DOTENV_VAR_NAME in os.environ
        assert os.environ[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '3'

    def test_load_env_var_defaults_load_start_first_no_chain(self, os_env_test_env):
        loaded = load_env_var_defaults(os_path_join(os_env_test_env, *((DOTENV_DIR_NAME,) * 3)), os.environ)

        assert DOTENV_VAR_NAME in loaded
        assert loaded[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '3'
        assert DOTENV_VAR_NAME in os.environ
        assert os.environ[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '3'

    def test_load_env_var_defaults_load_start_parent_first_in_chain(self, os_env_test_env):
        loaded = load_env_var_defaults(os_path_join(os_env_test_env, *((DOTENV_DIR_NAME,) * 2)), os.environ)

        assert DOTENV_VAR_NAME in loaded
        assert loaded[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '1'
        assert DOTENV_VAR_NAME in os.environ
        assert os.environ[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '1'

    def test_load_env_var_defaults_load_start_no_parent_first_in_chain(self, os_env_test_env):
        loaded = load_env_var_defaults(os_path_join(os_env_test_env, *((DOTENV_DIR_NAME,) * 1)), os.environ)

        assert DOTENV_VAR_NAME in loaded
        assert loaded[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '1'
        assert DOTENV_VAR_NAME in os.environ
        assert os.environ[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '1'

    def test_load_env_var_defaults_load_start_on_second_within_chain(self, os_env_test_env):
        loaded = load_env_var_defaults(os_path_join(os_env_test_env, *((DOTENV_DIR_NAME,) * 0)), os.environ)

        assert DOTENV_VAR_NAME in loaded
        assert loaded[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '0'
        assert DOTENV_VAR_NAME in os.environ
        assert os.environ[DOTENV_VAR_NAME] == DOTENV_VAR_VAL + '0'

    def test_load_env_var_defaults_resolve_vars_late(self, os_env_test_env):
        loaded = load_env_var_defaults(os_path_join(os_env_test_env, *((DOTENV_DIR_NAME,) * 1)), os.environ)

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

        loaded = load_env_var_defaults(os_path_join(os_env_test_env, *((DOTENV_DIR_NAME, ) * 3)), empty_env)

        assert DOTENV_LATE_VAR_PRE + '0' not in loaded
        assert DOTENV_LATE_VAR_PRE + '0' not in empty_env
        assert DOTENV_LATE_VAR_PRE + '1' not in loaded
        assert DOTENV_LATE_VAR_PRE + '1' not in empty_env
        assert DOTENV_LATE_VAR_PRE + '3' in loaded
        assert DOTENV_LATE_VAR_PRE + '3' in empty_env
        assert loaded[DOTENV_LATE_VAR_PRE + '3'] == DOTENV_LIT_VALUES[3]
        assert empty_env[DOTENV_LATE_VAR_PRE + '3'] == DOTENV_LIT_VALUES[3]

        write_file(os_path_join(os_env_test_env, *((DOTENV_DIR_NAME, ) * 2), '.env'), "# closing level 2 gap")

        loaded = load_env_var_defaults(os_path_join(os_env_test_env, *((DOTENV_DIR_NAME, ) * 3)), os.environ)

        assert DOTENV_LATE_VAR_PRE + '0' in loaded
        assert DOTENV_LATE_VAR_PRE + '0' in os.environ
        assert DOTENV_LATE_VAR_PRE + '1' in loaded
        assert DOTENV_LATE_VAR_PRE + '1' in os.environ
        assert DOTENV_LATE_VAR_PRE + '3' in loaded
        assert DOTENV_LATE_VAR_PRE + '3' in os.environ
        assert loaded[DOTENV_LATE_VAR_PRE + '3'] == DOTENV_LATE_VALUES[3]
        assert os.environ[DOTENV_LATE_VAR_PRE + '3'] == DOTENV_LATE_VALUES[3]

    def test_parse_dotenv_default_value_for_undefined_or_empty_var(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write('EMPTY_VAR = \n')
            fp.write('DECLARED_VAR = ${EMPTY_VAR:-DefaultValue}\n')
            fp.write('DECLARED_VAR2 = ${EMPTY_VAR-DefaultValue}\n')
            fp.write('VAR_NAME = ${UNDECLARED_VAR_NAME:-UndeclaredDefaultValue}\n')
            fp.write('VAR_NAME2 = ${UNDECLARED_VAR_NAME-UndeclaredDefaultValue}\n')
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'EMPTY_VAR' in loaded
            assert 'DECLARED_VAR' in loaded
            assert 'VAR_NAME' in loaded

            late_env_var_resolver(loaded, loaded, late_resolved)

            assert loaded['EMPTY_VAR'] == ""
            # Possix default values for empty/undeclared variables not fully supported (as has to be expanded by caller)
            assert loaded['DECLARED_VAR'] == "${EMPTY_VAR:-DefaultValue}"                   # "DefaultValue"
            assert loaded['DECLARED_VAR2'] == "${EMPTY_VAR-DefaultValue}"                   # "" (EMPTY_VAR value)
            assert loaded['VAR_NAME'] == "${UNDECLARED_VAR_NAME:-UndeclaredDefaultValue}"   # "UndeclaredDefaultValue"
            assert loaded['VAR_NAME2'] == "${UNDECLARED_VAR_NAME-UndeclaredDefaultValue}"   # "UndeclaredDefaultValue"

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

    def test_parse_dotenv_empty_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam=")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded

            late_env_var_resolver(loaded, loaded, late_resolved)

            assert loaded['var_nam'] == ""

    def test_parse_dotenv_error_space_prefixed_var_name(self, recwarn):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write(' var_nam="var val"')
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' not in loaded
            assert len(recwarn) == 1
            assert f"doesn't match {'.env'} format" in str(recwarn[0].message)

    def test_parse_dotenv_escaped_double_quote(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write('var_nam="escaped\\"val"')
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded

            late_env_var_resolver(loaded, loaded, late_resolved)

            assert loaded['var_nam'] == 'escaped"val'

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

    def test_parse_dotenv_expands_variables_found_in_values(self):
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

    def test_parse_dotenv_expands_variable_wrapped_in_brackets(self):
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

    def test_parse_dotenv_expands_not_an_undefined_variable_to_empty_string(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam=$env_var")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'env_var' not in loaded
            assert 'var_nam' in loaded

            late_env_var_resolver(loaded, loaded, late_resolved)

            assert loaded['var_nam'] == "$env_var"

    def test_parse_dotenv_expands_in_double_quoted_values(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("env_var=tst\nvar_nam=\"var val $env_var\"")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded

            late_env_var_resolver(loaded, loaded, late_resolved)

            assert loaded['var_nam'] == "var val tst"

    def test_parse_dotenv_expands_not_in_single_quoted_values(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam='var val $env_var'")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded

            late_env_var_resolver(loaded, loaded, late_resolved)

            assert loaded['var_nam'] == "var val $env_var"

    def test_parse_dotenv_expands_not_escaped_variables(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam=var val \\$env_var \\${env_var}")
            fp.seek(0)
            late_resolved = {}

            loaded = parse_dotenv(fp.name, late_resolved)

            assert 'var_nam' in loaded

            late_env_var_resolver(loaded, loaded, late_resolved)

            assert loaded['var_nam'] == "var val $env_var ${env_var}"

    def test_parse_dotenv_export_var_declaration(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("export var_nam=var val")
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == "var val"

    def test_parse_dotenv_inline_comments(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("VAL_WITH_HASH01=#VAL1\n"
                     "VAL_WITH_HASH02=VAL#2\n"
                     "VAL_WITH_HASH03='VAL3 #'\n"
                     "VAL_WITH_HASH04=\" #4 VAL #\"\n" 
                     "VAL_WITH_HASH11=#VAL1      \t# comment\n"
                     "VAL_WITH_HASH12=VAL#2        # comment\n"
                     "VAL_WITH_HASH13='VAL3 #' \t  # comment\n"
                     "VAL_WITH_HASH14=\"VAL #4 #\" #comment#\n" 
                     "EMPTY_VAL_COMMENT1= # comment\n"
                     "EMPTY_VAL_COMMENT2=\t#comment\n")
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert loaded['VAL_WITH_HASH01'] == "#VAL1"
            assert loaded['VAL_WITH_HASH02'] == "VAL#2"
            assert loaded['VAL_WITH_HASH03'] == "VAL3 #"
            assert loaded['VAL_WITH_HASH04'] == " #4 VAL #"
            assert loaded['VAL_WITH_HASH11'] == "#VAL1"
            assert loaded['VAL_WITH_HASH12'] == "VAL#2"
            assert loaded['VAL_WITH_HASH13'] == "VAL3 #"
            assert loaded['VAL_WITH_HASH14'] == "VAL #4 #"
            assert loaded['EMPTY_VAL_COMMENT1'] == ""
            assert loaded['EMPTY_VAL_COMMENT2'] == ""

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

    def test_parse_dotenv_multi_line_var_value_on_linux(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            var_val = "{'key': {'sub-key':\\\n    ['list-item',\\\n     'list-item with = char', ]}}"
            fp.write("var_nam=" + var_val)
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == var_val.replace('\\\n', "")

        # works also if the next/wrapped lines are not indented
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            var_val = "{'key': {'sub-key':\\\n['list-item',\\\n'list-item with = char', ]}}"
            fp.write("var_nam=" + var_val)
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == var_val.replace('\\\n', "")

    def test_parse_dotenv_multi_line_var_value_on_macos(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            var_val = "{'key': {'sub-key':\\\r    ['list-item',\\\r     'list-item with = char', ]}}"
            fp.write("var_nam=" + var_val)
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == var_val.replace('\\\r', "")

    def test_parse_dotenv_multi_line_var_value_on_win(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            var_val = "{'key': {'sub-key':\\\r\n    ['list-item',\\\r\n     'list-item with = char', ]}}"
            fp.write("var_nam=" + var_val)
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == var_val.replace('\\\r\n', "")

    def test_parse_dotenv_single_in_double_quoted_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write('''var_nam="'var val'"''')
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == "'var val'"

    def test_parse_dotenv_single_quote_in_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("""VAR_NAME='I\'m here'""")
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'VAR_NAME' in loaded
            assert loaded['VAR_NAME'] == "I'm here"

    def test_parse_dotenv_single_quote_bash_splices_unsupported(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("""VAR_NAME='I'"'"'m here'""")     # see issue https://github.com/theskumar/python-dotenv/pull/633
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'VAR_NAME' in loaded
            assert loaded['VAR_NAME'] == """I'"'"'m here"""     # w/ bash splices supported would result in "I'm here"

    def test_parse_dotenv_single_value(self):
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write("var_nam='var val'")
            fp.seek(0)

            loaded = parse_dotenv(fp.name, {})

            assert 'var_nam' in loaded
            assert loaded['var_nam'] == "var val"

    def test_parse_dotenv_start_parent_first_in_chain(self, os_env_test_env):
        assert DOTENV_VAR_NAME not in os.environ
        file_path = os_path_join(os_env_test_env, DOTENV_DIR_NAME, '.env')

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
    def test_module_attr_callable_with_args(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        namespace = "tst_nsn"
        mod_name = 'test_module_name'
        att_name = 'test_module_func'
        write_file(os_path_join(namespace, mod_name + '.py'),
                   f"def {att_name}(*args, **kwargs):\n    return args, kwargs\n",
                   make_dirs=True)
        args = (1, '2')
        kwargs = dict(kwarg1=1, kwarg2='2')

        ret = module_attr(namespace + '.' + mod_name, att_name)
        assert ret
        assert callable(type(ret))

        call_ret = ret(*args, **kwargs)
        assert call_ret
        assert call_ret[0] == args
        assert call_ret[1] == kwargs

        # test already imported module another module_attr() call after load of non-registered module
        callee = module_attr('textwrap', 'indent')
        assert callable(callee)
        assert callee is textwrap.indent

    def test_module_attr_callable_wrong_args(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        namespace = "nsn_tst"
        mod_name = 'test_module_name'
        att_name = 'test_module_func'
        write_file(os_path_join(namespace, mod_name + '.py'),
                   f"def {att_name}(arg1, args2, kwarg1='default'):\n    return arg1, arg2, kwarg1\n",
                   make_dirs=True)

        callee = module_attr(namespace + '.' + mod_name, att_name)
        assert callable(callee)

        args = (1, '2')
        kwargs = dict(kwarg1=1, kwarg2='2')
        with pytest.raises(TypeError):
            callee(*args, **kwargs)

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
        module_file = os_path_join(namespace, mod_name + '.py')

        write_file(module_file, f"# unregistered tst module\n{attr_nam} = {attr_val}")

        assert module_attr(namespace + '.' + mod_name, attr_nam) == attr_val

        monkeypatch.chdir(namespace)

        assert module_attr(mod_name, attr_nam) == attr_val

    def test_module_attr_not_exists_attr(self, monkeypatch, tmp_path):
        """ first test with a non-existing module, second test with a non-existing function. """
        namespace = str(tmp_path)
        mod_name = 'test_module_name'
        att_name = 'test_module_func'
        module_file = os_path_join(namespace, mod_name + '.py')
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

    def test_module_file_path_with_mocked_stack_var(self):
        with patch('ae.system.stack_var', return_value=""):
            assert module_file_path() == __file__

    def test_module_file_path_without_dunder_file_exception(self):
        with (patch('ae.system.stack_var', return_value=""),
              patch('ae.system.sys._getframe', side_effect=Exception())):
            assert module_file_path() == ""

    def test_module_find_builtins(self):
        path_or_err = module_find('textwrap')
        assert isinstance(path_or_err, str)

        path_or_err = module_find('os.path')
        assert isinstance(path_or_err, str)

        path_or_err = module_find('os')
        assert isinstance(path_or_err, str)

    def test_module_find_local_module(self, monkeypatch, tmp_path):
        module = "tst_mod_nam"
        mod_file = os_path_join(str(tmp_path), module + '.py')
        write_file(mod_file, f"# module_find test module\nsome_var = 'some_var_val'")

        assert isinstance(module_find(module), list)    # not found because neither under sys.path nor in sys.modules

        monkeypatch.syspath_prepend(str(tmp_path))

        mod_path = module_find(module)

        assert isinstance(mod_path, str)

    def test_module_find_spec_exception(self):
        with patch('ae.system.importlib.util.find_spec', side_effect=ValueError):
            errors = module_find('tst_import_name')
            assert isinstance(errors, list) and len(errors) == 1
            assert 'tst_import_name' in errors[0]

    def test_module_find_submodule_search_locations(self):
        spec_mock = MagicMock()
        spec_mock.origin = None
        spec_mock.loader_state = None
        spec_mock.submodule_search_locations = ['tst_file_path']
        with patch('ae.system.importlib.util.find_spec', return_value=spec_mock):
            assert module_find('import_name') == 'tst_file_path'

    def test_module_find_with_module_path_not_found(self):
        spec_mock = MagicMock()
        spec_mock.origin = 'frozen'
        spec_mock.loader_state = None
        spec_mock.submodule_search_locations = None
        with patch('ae.system.importlib.util.find_spec', return_value=spec_mock):
            assert module_find('import_name') == [f"path not available for {spec_mock.origin + '-'}module import_name"]

    def test_module_load_builtins(self):
        assert isinstance(module_load('textwrap'), ModuleType)
        assert isinstance(module_load('os.path'), ModuleType)
        assert isinstance(module_load('os'), ModuleType)

    def test_module_load_error(self):
        with patch('ae.system.importlib.util.module_from_spec'):
            err = module_load('os')
            assert isinstance(err, list) and len(err) == 1
            assert "is not of importlib.abs.loader" in err[0]

    def test_module_load_exception(self):
        with patch('ae.system.importlib.util.module_from_spec', side_effect=FileNotFoundError):
            err = module_load('os')
            assert isinstance(err, list) and len(err) == 1
            assert "'os'" in err[0]

    def test_module_load_local_module(self, monkeypatch, tmp_path):
        module = "mod_2_tst"
        mod_file = os_path_join(str(tmp_path), module + '.py')
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

        mod_ref = module_load(module, path=module + '.py')

        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

        mod_ref = module_load(module)

        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'mod_var') == 'mod_var_val'

    def test_module_load_local_package(self, monkeypatch, tmp_path):
        namespace = "y_xx"
        portion = "por_2_tst"

        pkg_path = os_path_join(str(tmp_path), namespace, portion)
        pkg_file = os_path_join(pkg_path, '__init__' + '.py')
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

        mod_ref = module_load(namespace + '.' + portion, path=os_path_relpath(pkg_file, str(tmp_path)))

        assert isinstance(mod_ref, ModuleType)
        assert getattr(mod_ref, 'pkg_var') == 'pkg_var_val'

    def test_module_load_not_exists(self):
        assert (err_or_mod := module_load('not_existing_import_name'))
        assert isinstance(err_or_mod, list)


class TestOsDeviceId:
    @pytest.fixture(autouse=True)
    def reset_module(self):
        yield
        importlib.reload(ae.system)

    def test_os_device_id_for_android(self):
        mock_jnius = MagicMock()
        mock_class = MagicMock()
        mock_class.getString.return_value = 'android_device_id'
        mock_jnius.autoclass.side_effect = lambda name: mock_class if 'Settings' in name else MagicMock()
        with (patch.dict('os.environ', {'ANDROID_ARGUMENT': '1'}),
              patch.dict('sys.modules', {'jnius': mock_jnius})):
            importlib.reload(ae.system)
            assert ae.system.os_device_id == 'android_device_id'

    def test_os_device_id_for_android_empty_and_exception(self):
        mock_jnius = MagicMock()
        mock_class = MagicMock()
        mock_class.getString.return_value = ""  # empty device_name
        mock_jnius.autoclass.side_effect = lambda name: mock_class if 'Settings' in name else MagicMock()
        with (patch.dict('os.environ', {'ANDROID_ARGUMENT': '1'}),
              patch('ae.system.platform.node', return_value='tst_default_id'),
              patch.dict('sys.modules', {'jnius': mock_jnius})):
            importlib.reload(ae.system)
            assert ae.system.os_device_id == 'tst_default_id'

        mock_jnius_exc = MagicMock()
        mock_jnius_exc.autoclass.side_effect = Exception("Android API tst error")   # fallback to os_host_name()
        with patch.dict('os.environ', {'ANDROID_ARGUMENT': '1'}), \
             patch('ae.system.platform.node', return_value='tst_default_id'), \
             patch.dict('sys.modules', {'jnius': mock_jnius_exc}):
            importlib.reload(ae.system)
            assert ae.system.os_device_id == 'tst_default_id'

    def test_os_device_id_for_linux_and_mac(self):
        with patch('ae.system.platform.node', return_value='tst_default_id'):
            importlib.reload(ae.system)
            assert ae.system.os_device_id == 'tst_default_id'   # defaults to os_host_name()/platform.node()

    def test_os_device_id_for_win32(self):
        with (patch('sys.platform', 'win32'),
              patch.dict('os.environ', {'COMPUTERNAME': 'tst_name'})):
            importlib.reload(ae.system)
            assert ae.system.os_device_id == 'tst_name'

    def test_os_device_id_for_win32_no_computername(self):
        clean_env = {k: v for k, v in os.environ.items() if k != 'COMPUTERNAME'}
        with (patch('sys.platform', 'win32'),
              patch('ae.system.platform.node', return_value='tst_default_id'),
              patch.dict('os.environ', clean_env, clear=True)):
            importlib.reload(ae.system)
            assert ae.system.os_device_id == 'tst_default_id'

    def test_os_device_id_if_platform_node_fails(self):
        mock_jnius = MagicMock()
        mock_settings = MagicMock()
        mock_settings.getString.return_value = ""                               # empty device name on Android
        mock_jnius.autoclass.return_value = mock_settings
        with (patch('ae.system.platform.node', return_value=""),                # empty device name on Linux/Mac
              patch.dict('os.environ', {'COMPUTERNAME': ''}, clear=False),      # empty device name on Windows
              patch.dict('sys.modules', {'jnius': mock_jnius})):
            importlib.reload(ae.system)
            assert ae.system.os_device_id == 'indeterminableHostName'


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


class TestVenvCI:     # venv tests that are running also on the repo/CI host for full test coverage
    def test_os_env_venv(self):
        with (patch('ae.system.venv_prefix', return_value=""),
              patch('ae.system.os.getenv', return_value="")):
            assert os_env_venv() == ""

        with patch('ae.system.os.getenv', return_value=""):
            assert os_env_venv() == ""

        with patch('ae.system.os.getenv', return_value='venv_tst_nam'):
            assert os_env_venv() == 'venv_tst_nam'

        with patch('ae.system.os.getenv', return_value='/path/to/venv_tst_nam/'):
            assert os_env_venv() == 'venv_tst_nam'

        with patch('ae.system.os.getenv', return_value='C:\\path/to\\venv_tst_nam\\'):
            assert os_env_venv() == 'venv_tst_nam'

    def test_venv_prefix(self):
        with patch('ae.system.os.getenv', return_value='venv_tst_nam'):
            assert venv_prefix().endswith('venv_tst_nam')

        with patch('ae.system.os.getenv', return_value='path/to/venv_tst_nam1'):
            assert venv_prefix().endswith('venv_tst_nam1')

        with patch('ae.system.os.getenv', return_value='/absolute/path/to/venv_tst_nam2/'):
            assert venv_prefix().endswith('venv_tst_nam2')

        with patch('ae.system.os.getenv', return_value=""):
            assert venv_prefix() == ""


@skip_gitlab_ci  # venv tests that run only on local machine with an activated VENV
class TestVenvIntegration:
    def test_integration_system_environment(self):
        assert os.getenv('VIRTUAL_ENV') or os.getenv('CONDA_PREFIX'), "activated VENV is needed for integration tests"

    def test_os_env_venv(self):
        assert os_env_venv()

        with (patch('ae.system.venv_prefix', return_value=""),
              patch('ae.system.os.getenv', return_value="")):
            assert os_env_venv() == ""

    def test_venv_prefix(self):
        assert venv_prefix() == norm_path(os.getenv('VIRTUAL_ENV', os.getenv('CONDA_PREFIX', venv_prefix())))

        with patch('ae.system.os.getenv', return_value=""):
            assert venv_prefix() == ""
