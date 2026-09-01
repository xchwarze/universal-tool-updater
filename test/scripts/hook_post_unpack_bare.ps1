# Test hook: wired as "post_unpack" on FixtureNested using a BARE .ps1
# path (no launcher prefix). Regression test for the fix that lets a
# bare .ps1 script be auto-wrapped with
# "powershell -NoProfile -ExecutionPolicy Bypass -File ...".
#
# post_unpack scripts receive tool_name, unpack_folder, download_version
# as positional args.
$line = "{0} hook_post_unpack_bare.ps1 args=[{1}]" -f (Get-Date -Format o), ($args -join ' ')
Add-Content -Path markers.log -Value $line
