import subprocess
import shlex
import pathlib
import colorama
import logging


class ScriptExecutor:
    """
    Class responsible for executing scripts during the update process.
    """

    def __init__(self, config_manager=None):
        """
        Initialize ScriptExecutor.

        :param config_manager: Configuration manager instance, used to read global settings
        """
        self.tool_name = ""
        self.tool_config = {}
        self.config_manager = config_manager
        self.valid_types = ['post_unpack', 'pre_update', 'post_update']

    def tool_setup(self, tool_name, tool_config):
        """
        Initialize tool-specific settings.

        :param tool_name: Name of the tool
        :param tool_config: Configuration object for the specific tool
        """
        self.tool_name = tool_name
        self.tool_config = tool_config

    def _build_command(self, script):
        """
        Build a proper argv list from a configured script/command string.

        :param script: Raw script or command string from tools.ini
        :return: List of argv parts, prefixed for PowerShell execution if the script is a .ps1 file
        """
        raw_parts = shlex.split(script, posix=False)
        parts = [
            part[1:-1] if len(part) >= 2 and part[0] == '"' and part[-1] == '"' else part
            for part in raw_parts
        ]
        if parts and pathlib.Path(parts[0]).suffix.lower() == '.ps1':
            return ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', *parts]

        return parts

    def _run(self, label, script, params):
        """
        Run a resolved script command with shared logging and error handling.

        :param label: Human-readable name for this script, used in log messages
        :param script: Raw script/command string to execute
        :param params: Iterable of extra argv parameters to append after the command
        """
        logging.info(f'{self.tool_name}: exec {label} "{script}"')
        logging.info(colorama.Fore.BLUE + '------------------------------')

        try:
            subprocess.run([*self._build_command(script), *params], check=True)
        except subprocess.CalledProcessError as error:
            logging.error(f'{self.tool_name}: {label} exited with code {error.returncode}')
        except Exception as exception:
            logging.error(f'{self.tool_name}: failed to execute {label}: {exception}')

        logging.info(colorama.Fore.BLUE + '------------------------------')

    def execute_script(self, script_type, script_params = None):
        """
        Execute a specific script for a given tool.

        :param script_type: Type of script to execute ('pre_update', 'post_update', 'post_unpack')
        :param script_params: Optional dict of parameters to pass to the script as args
        """
        if script_type in self.valid_types and script_type in self.tool_config:
            script = self.tool_config[script_type]
            params = script_params.values() if script_params else []
            self._run(f'{script_type} script', script, params)

    def execute_global_script(self, script_params):
        """
        Execute a global script.

        :param script_params: Dict of parameters to pass to the script as args
        """
        script = self.config_manager.get_config('UpdaterConfig', 'global_post_update', fallback=None) if self.config_manager else None
        if script:
            self._run('global script', script, script_params.values())
