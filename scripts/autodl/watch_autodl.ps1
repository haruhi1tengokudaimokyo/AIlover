$Host.UI.RawUI.WindowTitle = 'AIlover AutoDL - 实时下载与正式训练进度'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$connection = Get-Content -LiteralPath (Join-Path $PSScriptRoot '../../runtime/cloud-connection.json') -Raw | ConvertFrom-Json
& ssh -tt -i $connection.key -p $connection.port -o BatchMode=yes -o ServerAliveInterval=30 $connection.host '/root/miniconda3/bin/python -u /root/autodl-tmp/ailover/code/watch_remote.py'
