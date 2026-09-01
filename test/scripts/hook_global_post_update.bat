@ECHO OFF
REM Test hook: wired as "global_post_update" under [UpdaterConfig].
REM Fires once per successfully updated tool, for every tool in the run.
echo %date% %time% hook_global_post_update.bat args=[%*] >> markers.log
