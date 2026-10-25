$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$workerPath = Join-Path $PSScriptRoot 'update_market_data.py'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Existing project Python environment is required.' }
$taskName = 'TradersGita-MarketData'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Actions.Execute -ne $pythonPath) { throw 'Task name is already used by a different program.' }
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument ('"' + $workerPath + '"') -WorkingDirectory $projectRoot
# Explicit IST offset keeps the schedule correct even if Windows uses another timezone.
$triggerXml = '<CalendarTrigger><Repetition><Interval>PT1H</Interval><Duration>PT4H</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>2026-10-25T18:30:00+05:30</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 30) -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$task = New-ScheduledTask -Action $action -Principal $principal -Settings $settings -Description 'NSE BHAV daily catch-up and selected-stock intraday candles; 18:30 IST with evening retries.'
$xml = [xml](Export-ScheduledTask -InputObject $task)
$ns = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
$ns.AddNamespace('t', $xml.DocumentElement.NamespaceURI)
$triggers = $xml.SelectSingleNode('//t:Triggers', $ns)
$fragment = $xml.CreateDocumentFragment()
$fragment.InnerXml = $triggerXml.Replace('<CalendarTrigger>', '<CalendarTrigger xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">')
[void]$triggers.AppendChild($fragment)
Register-ScheduledTask -TaskName $taskName -Xml $xml.OuterXml -Force | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object NextRunTime, LastTaskResult
