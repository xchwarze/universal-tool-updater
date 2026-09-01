"""
Unit tests for ScriptExecutor._build_command.
"""

from universal_updater.ScriptExecutor import ScriptExecutor


def make_executor():
    return ScriptExecutor()


def test_quoted_path_with_spaces_and_arg_strips_quotes():
    executor = make_executor()

    result = executor._build_command(r'"C:\Program Files\tool\run.bat" --flag')

    assert result == [r'C:\Program Files\tool\run.bat', '--flag']


def test_quoted_ps1_path_is_detected_and_wrapped_for_powershell():
    executor = make_executor()

    result = executor._build_command(r'"C:\scripts\hook.ps1"')

    assert result == [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        r'C:\scripts\hook.ps1',
    ]


def test_quoted_ps1_path_with_args_is_wrapped_and_keeps_args():
    executor = make_executor()

    result = executor._build_command(r'"C:\scripts\hook.ps1" arg1 arg2')

    assert result == [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        r'C:\scripts\hook.ps1', 'arg1', 'arg2',
    ]


def test_plain_unquoted_path_stays_single_element_list():
    executor = make_executor()

    result = executor._build_command(r'C:\tools\run.bat')

    assert result == [r'C:\tools\run.bat']


def test_unquoted_multiword_command_splits_into_multiple_tokens():
    executor = make_executor()

    result = executor._build_command(r'C:\tools\run.bat --flag value')

    assert result == [r'C:\tools\run.bat', '--flag', 'value']


def test_unquoted_ps1_path_without_extension_case_is_still_detected():
    # suffix check uses .lower(), so a differently-cased .PS1 extension
    # must still be recognized and wrapped.
    executor = make_executor()

    result = executor._build_command(r'C:\scripts\hook.PS1')

    assert result == [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        r'C:\scripts\hook.PS1',
    ]


def test_non_ps1_script_is_not_wrapped():
    executor = make_executor()

    result = executor._build_command(r'C:\scripts\hook.bat')

    assert result == [r'C:\scripts\hook.bat']
