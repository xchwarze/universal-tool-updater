@ECHO OFF
REM Test hook: wired as "pre_update" on FixtureWeb.
REM pre_update scripts receive no extra arguments from ScriptExecutor.
echo %date% %time% hook_pre_update.bat args=[%*] >> markers.log
