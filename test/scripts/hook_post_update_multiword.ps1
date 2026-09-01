# Test hook: wired as "post_update" on FixtureMerge via a MULTI-WORD
# command string:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hook_post_update_multiword.ps1
# Regression test for launching a "command with arguments as one string"
# (shlex.split(script, posix=False) must tokenize this correctly) as
# opposed to the bare-.ps1-path auto-wrap path exercised by
# hook_post_unpack_bare.ps1.
$line = "{0} hook_post_update_multiword.ps1 args=[{1}]" -f (Get-Date -Format o), ($args -join ' ')
Add-Content -Path markers.log -Value $line
