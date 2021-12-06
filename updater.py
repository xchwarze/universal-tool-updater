# -*- coding: utf-8  -*-
#
# Copyright (C) 2021 DSR! <xchwarze@gmail.com>
# Released under the terms of the MIT License
# Developed for Python 3.6+
# pip install requests py7zr

import argparse
import configparser
import requests
import re
import os
import shutil
import pathlib
import zipfile
import py7zr
import subprocess


# Helpers functions
def get_filename_from_url(url):
    fragment_removed = url.split('#')[0]  # keep to left of first #
    query_string_removed = fragment_removed.split('?')[0]
    scheme_removed = query_string_removed.split('://')[-1].split(':')[-1]

    if scheme_removed.find('/') == -1:
        return ''

    return pathlib.Path(scheme_removed).name

def cleanup_folder(path):
    for file in pathlib.Path(path).iterdir():
        if file.is_dir():
            shutil.rmtree(file)
        else:
            file.unlink()

def download(url, file_path):
    file_response = requests.get(url, allow_redirects=True, stream=True)
    file_response.raise_for_status()

    # for debug redirects
    #print('DEBUG: download url "{0}"'.format(file_response.url))

    with open(file_path, 'wb') as handle:
        for block in file_response.iter_content(1024):
            handle.write(block)

def unpack(file_path, file_ext, unpack_path, file_pass):
    if file_ext == '.zip':
        if file_pass:
            file_pass = bytes(file_pass, 'utf-8')

        with zipfile.ZipFile(file_path, 'r') as compressed:
            compressed.extractall(unpack_path, pwd=file_pass)

    elif file_ext == '.7z':
        with py7zr.SevenZipFile(file_path, 'r', password=file_pass) as compressed:
            compressed.extractall(unpack_path)

    else:
        pathlib.Path(unpack_path).mkdir(exist_ok=True)
        shutil.copy(file_path, unpack_path)


# Main Updater class
class Updater:
    def __init__(self, config, force_download, no_repack, no_clean):
        self.name = ''
        self.config = config
        self.force_download = force_download
        self.no_repack = no_repack
        self.no_clean = no_clean
        self.script_path = os.fsdecode(os.getcwdb())
        self.update_folder_path = pathlib.Path(self.script_path).joinpath('updates')

    def _check_version_from_web(self, html):
        local_version = self.config.get(self.name, 'local_version', fallback='0')
        re_version = self.config.get(self.name, 're_version')
        html_regex_version = re.findall(re_version, html)

        if not html_regex_version:
            raise Exception('{0}: re_version regex not match'.format(self.name))

        if not self.force_download and local_version == html_regex_version[0]:
            raise Exception('{0}: {1} is the latest version'.format(self.name, local_version))

        print('{0}: updated from {1} --> {2}'.format(self.name, local_version, html_regex_version[0]))

        return html_regex_version[0]

    def _get_download_url_from_web(self, html):
        update_url = self.config.get(self.name, 'update_url', fallback=None)
        re_download = self.config.get(self.name, 're_download', fallback=None)

        # case 2: if update_url is not set, scrape the link from html
        if re_download:
            html_regex_download = re.findall(re_download, html)
            if not html_regex_download:
                raise Exception('{0}: re_download regex not match'.format(self.name))

            # case 3: if update_url and re_download is set.... generate download link
            if update_url:
                update_url = '{0}{1}'.format(update_url, html_regex_download[0])
            else:
                update_url = html_regex_download[0]

        # case 1: if update_url is set... download it!
        if not update_url:
            raise Exception('{0}: update_url not generated!'.format(self.name))

        return update_url

    def _scrape_web(self):
        web_url = self.config.get(self.name, 'url')

        # load html
        html_response = requests.get(web_url)
        html_response.raise_for_status()

        return {
            # regex shit
            'download_version': self._check_version_from_web(html_response.text),
            'download_url': self._get_download_url_from_web(html_response.text),
        }

    def _check_version_from_github(self, json):
        local_version = self.config.get(self.name, 'local_version', fallback='0')

        if not self.force_download and local_version == json['tag_name']:
            raise Exception('{0}: {1} is the latest version'.format(self.name, local_version))

        print('{0}: updated from {1} --> {2}'.format(self.name, local_version, json['tag_name']))

        return json['tag_name']

    def _get_download_url_from_github(self, json):
        re_download = self.config.get(self.name, 're_download', fallback=None)

        if not re_download:
            raise Exception('{0}: re_download regex not set'.format(self.name))

        update_url = None
        for attachment in json['assets']:
            html_regex_download = re.findall(re_download, attachment['browser_download_url'])
            if html_regex_download:
                update_url = attachment['browser_download_url']
                break

        if not update_url:
            raise Exception('{0}: re_download regex not match'.format(self.name))

        return update_url

    def _scrape_github(self):
        repo_path = self.config.get(self.name, 'url')
        web_url = 'https://api.github.com/repos/{0}/releases/latest'.format(repo_path)

        # load json
        html_response = requests.get(web_url)
        html_response.raise_for_status()
        json_response = html_response.json()

        return {
            # regex shit
            'download_version': self._check_version_from_github(json_response),
            'download_url': self._get_download_url_from_github(json_response),
        }

    def _repack(self, unpack_path, version):
        tool_unpack_path = unpack_path

        # dirty hack for correct folders structure
        folder_list = os.listdir(tool_unpack_path)
        folder_sample = pathlib.Path(tool_unpack_path).joinpath(folder_list[0])
        if len(folder_list) == 1 & os.path.isdir(folder_sample):
            tool_unpack_path = folder_sample

        # update tool
        tool_folder = self.config.get(self.name, 'folder')
        if not pathlib.Path(tool_folder).is_absolute():
            tool_folder = pathlib.Path.resolve( pathlib.Path(self.script_path).joinpath(tool_folder) )

        print('{0}: saved to {1}'.format(self.name, tool_folder))
        pathlib.Path(tool_folder).mkdir(parents=True, exist_ok=True)

        if not self.no_clean:
            cleanup_folder(tool_folder)

        if self.no_repack:
            shutil.copytree(tool_unpack_path, tool_folder, copy_function=shutil.copy, dirs_exist_ok=True)
        else:
            tool_name = '{0} - {1}.7z'.format(self.name, version)
            tool_repack_path = pathlib.Path( pathlib.Path(unpack_path).parent ).joinpath(tool_name)

            with py7zr.SevenZipFile(tool_repack_path, 'w') as archive:
                archive.writeall(tool_unpack_path, arcname='')

            shutil.copy(tool_repack_path, tool_folder)

    def _bump_version(self, latest_version):
        self.config.set(self.name, 'local_version', latest_version)
        with open('tools.ini', 'w') as configfile:
            self.config.write(configfile)

    def _exec_update_script(self, script_type):
        script = self.config.get(self.name, script_type, fallback=None)
        if script:
            print('{0}: exec {1} "{2}"'.format(self.name, script_type, script))
            print('------------------------------')
            subprocess.run(script)
            print('------------------------------')

    def _scrape_step(self):
        from_url = self.config.get(self.name, 'from', fallback='web')
        if from_url == 'github':
            return self._scrape_github()

        return self._scrape_web()

    def _download_step(self, download_url):
        # create updates folder if dont exist
        if not pathlib.Path.exists(self.update_folder_path):
            pathlib.Path.mkdir(self.update_folder_path)

        # download
        file_name = get_filename_from_url(download_url)
        file_path = pathlib.Path(self.update_folder_path).joinpath(file_name)

        print('{0}: downloading update "{1}"'.format(self.name, file_name))
        self.cleanup_update_folder()
        download(download_url, file_path)

        return file_path

    def _processing_step(self, file_path, download_version):
        file_ext = pathlib.Path(file_path).suffix
        update_folder = str(file_path).replace(file_ext, '')

        update_file_pass = self.config.get(self.name, 'update_file_pass', fallback=None)
        unpack_path = pathlib.Path(self.update_folder_path).joinpath(update_folder)
        unpack(file_path, file_ext, unpack_path, update_file_pass)

        self._exec_update_script('post_unpack')
        self._repack(unpack_path, download_version)

    def update(self, name):
        self.name = name

        # execute custom pre update script
        self._exec_update_script('pre_update')

        # generate download url
        scrape_data = self._scrape_step()

        # download
        update_file_path = self._download_step(scrape_data['download_url'])

        # processing file
        print('{0}: processing file'.format(self.name))
        self._processing_step(update_file_path, scrape_data['download_version'])

        # update complete
        self._bump_version(scrape_data['download_version'])
        self._exec_update_script('post_update')
        print('{0}: update complete\n'.format(self.name))

    def cleanup_update_folder(self):
        cleanup_folder(self.update_folder_path)


# Implementation
class Setup:
    def __init__(self):
        self.arguments = {}
        self.config = configparser.ConfigParser()

    def print_banner(self):
        print("""
        ____          __     __            __        __    __         
       /  _/___  ____/ /__  / /____  _____/ /_____ _/ /_  / /__  _____
       / // __ \/ __  / _ \/ __/ _ \/ ___/ __/ __ `/ __ \/ / _ \/ ___/
     _/ // / / / /_/ /  __/ /_/  __/ /__/ /_/ /_/ / /_/ / /  __(__  ) 
    /___/_/ /_/\__,_/\___/\__/\___/\___/\__/\__,_/_.___/_/\___/____/  
    
    Universal Tool Updater - by DSR!
    https://github.com/xchwarze/universal-tool-updater
    """)

    def init_argparse(self):
        parser = argparse.ArgumentParser(
            usage='%(prog)s [ARGUMENTS]',
        )
        parser.add_argument(
            '-v',
            '--version',
            action='version',
            version='version 1.5.0'
        )
        parser.add_argument(
            '-u',
            '--update',
            dest='update',
            help='update tools (default: all)',
            nargs='*'
        )
        parser.add_argument(
            '-dfc',
            '--disable-folder-clean',
            dest = 'disable_folder_clean',
            help = 'disable tool folder clean (default: no_disable_folder_clean)',
            action = argparse.BooleanOptionalAction,
            default = False
        )
        parser.add_argument(
            '-dr',
            '--disable-repack',
            dest = 'disable_repack',
            help = 'disable tool repack (default: no_disable_repack)',
            action = argparse.BooleanOptionalAction,
            default = False
        )
        parser.add_argument(
            '-f',
            '--force',
            dest = 'force',
            help = 'force download (default: no_force)',
            action = argparse.BooleanOptionalAction,
            default = False
        )

        self.arguments = parser.parse_args()

    def handle_updates(self, update_list):
        updater = Updater(
            config = self.config,
            force_download = self.arguments.force,
            no_repack = self.arguments.disable_repack,
            no_clean = self.arguments.disable_folder_clean
        )

        for ini_name in update_list:
            try:
                updater.update(ini_name)
            except Exception as exception:
                print(exception)

        updater.cleanup_update_folder()

    def main(self):
        self.print_banner()
        self.config.read('tools.ini')
        self.init_argparse()

        update_list = self.arguments.update
        if not self.arguments.update:
            update_list = self.config.sections()

        self.handle_updates(
            update_list = update_list,
        )

# se fini
Setup().main()
