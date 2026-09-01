import configparser
import os
import pathlib
import tempfile
import threading
import colorama


class ConfigManager:
    """
    Manages configuration settings, including getting and setting values,
    as well as updating the local version of a tool.
    """

    def __init__(self, config_file_name):
        """
        Initialize with the name of the config file.

        :param config_file_name: Name of the configuration file
        """
        self.config = configparser.ConfigParser(interpolation=None)
        self.config_file_name = config_file_name
        self._lock = threading.Lock()
        self.config.read(self.config_file_name, encoding='utf-8')

    def get_config(self, section, key, fallback=None):
        """
        Get a configuration value.

        :param section: Section in the config file
        :param key: Key in the section
        :param fallback: Fallback value if key is not found
        :return: Value of the configuration key
        """
        with self._lock:
            return self.config.get(section, key, fallback=fallback)

    def set_config(self, section, key, value):
        """
        Set a configuration value.

        :param section: Section in the config file
        :param key: Key in the section
        :param value: Value to set
        """
        self.set_many(section, {key: value})

    def set_many(self, section, values):
        """
        Set multiple configuration values in one write.

        :param section: Section in the config file
        :param values: Dict of key -> value to set
        """
        with self._lock:
            if not self.config.has_section(section):
                self.config.add_section(section)

            for key, value in values.items():
                self.config.set(section, key, value)

            self._write_config()

    def get_tool_config(self, name):
        """
        Retrieve the configuration for a specific tool.

        :param name: Name of the tool
        :return: Dictionary containing the tool's configuration
        """
        with self._lock:
            if name in self.config.sections():
                return dict(self.config.items(name))

        raise Exception(colorama.Fore.RED + f'No entries were found for {name}')

    def get_boolean(self, section, option, fallback=None):
        """
        Get a boolean configuration value. An unrecognized value (e.g. a typo
        like "maybe") falls back instead of raising, same as a missing key.

        :param section: Section in the config file
        :param option: Option in the section
        :param fallback: Fallback value if option is not found or invalid
        :return: Boolean value of the configuration option
        """
        with self._lock:
            try:
                return self.config.getboolean(section, option, fallback=fallback)
            except ValueError:
                return fallback

    def get_sections(self):
        """
        Get all sections in the configuration file.

        :return: List of section names
        """
        with self._lock:
            return self.config.sections()

    def update_local_version(self, name, version):
        """
        Update the local version of a tool in the configuration file.

        :param name: Name of the tool
        :param version: New version to update
        """
        self.set_config(name, 'local_version', version)

    def _write_config(self):
        """
        Write the current configuration to file (caller must hold the lock).
        Writes to a temp file first and atomically replaces the target, so a
        crash or encoding error mid-write never corrupts the existing file.
        """
        config_path = pathlib.Path(self.config_file_name)
        fd, tmp_path = tempfile.mkstemp(
            dir=config_path.parent,
            prefix=f'.{config_path.name}.',
            suffix='.tmp',
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as tmp_file:
                self.config.write(tmp_file)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, self.config_file_name)
        except Exception:
            pathlib.Path(tmp_path).unlink(missing_ok=True)
            raise
