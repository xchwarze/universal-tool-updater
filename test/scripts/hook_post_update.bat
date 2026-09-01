@ECHO OFF
REM Test hook: wired as "post_update" on FixtureWeb.
REM post_update scripts receive tool_name, tool_folder, save_compress_name
REM as positional args.
echo %date% %time% hook_post_update.bat args=[%*] >> markers.log
