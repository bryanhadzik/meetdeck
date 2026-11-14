<#
  MeetDeck launcher: start / stop / update MeetDeck, and start / stop the CTS console
  tools (emulator, tap to the real console, listen-only) without typing commands.

  Lives in MeetDeck\app\tools (updates replace it); "MeetDeck Launcher.cmd" in the
  MeetDeck folder opens it. Windows PowerShell 5.1 (built into Windows 10/11).
#>
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$Here   = $PSScriptRoot; if (-not $Here) { $Here = Split-Path -Parent $MyInvocation.MyCommand.Path }
$Root   = (Resolve-Path (Join-Path $Here '..\..')).Path          # ...\MeetDeck
$App    = Join-Path $Root 'app'
$Py     = Join-Path $Root 'python\python.exe'
$PyW    = Join-Path $Root 'python\pythonw.exe'
$Timing = Join-Path $App 'timing'
$Data   = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'MeetDeck'
# logs and captures go in Documents\MeetDeck\timing, which updates don't replace
$TimingData = Join-Path $Data 'timing'
$env:MEETDECK_DATA = $Data
$Url    = 'http://127.0.0.1:8001/'
$Repo   = 'bryanhadzik/meetdeck'
$script:ToolProc = $null

# ---------------------------------------------------------------- helpers
function Get-Version { try { (Get-Content (Join-Path $App 'VERSION') -Raw).Trim() } catch { '?' } }

function Test-Running {
    try { $r = Invoke-WebRequest ($Url + 'api/settings') -UseBasicParsing -TimeoutSec 2; return $r.StatusCode -eq 200 } catch { return $false }
}

function Get-MeetDeckProcs {
    @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like '*start.py*' -and $_.ExecutablePath -like "$Root*" })
}

function Get-ToolProcs {
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like '*emulator.py*' })
}

function Start-MeetDeck {
    if (Test-Running) { Start-Process $Url; return }
    Start-Process -FilePath $PyW -ArgumentList '-X', 'utf8', "`"$(Join-Path $Root 'start.py')`"" -WorkingDirectory $Root
    Set-Status 'Starting MeetDeck...'
}

function Stop-MeetDeck {
    foreach ($p in Get-MeetDeckProcs) { try { Stop-Process -Id $p.ProcessId -Force } catch { } }
    Start-Sleep -Milliseconds 800
}

function Get-Ports {
    $names = @([System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object { [int]($_ -replace '\D', '0') } -Unique)
    $desc = @{}
    try {
        Get-CimInstance Win32_PnPEntity -Filter "Name LIKE '%(COM%'" | ForEach-Object {
            if ($_.Name -match '\((COM\d+)\)') { $desc[$Matches[1]] = $_.Name }
        }
    } catch { }
    foreach ($n in $names) { if ($desc[$n]) { $desc[$n] } else { $n } }
}

function PortOf($text) { if ($text -match '(COM\d+)') { $Matches[1] } else { ($text -as [string]).Trim() } }

function Update-MeetDeck {
    Set-Status 'Checking GitHub for a newer MeetDeck...'
    $rel = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ 'User-Agent' = 'MeetDeck-launcher' }
    $latest = ($rel.tag_name -replace '^v', '')
    $cur = Get-Version
    if ($latest -eq $cur) { Set-Status "MeetDeck $cur is the newest."; return }
    $asset = $rel.assets | Where-Object { $_.name -like 'meetdeck-app-*.zip' } | Select-Object -First 1
    if (-not $asset) { Set-Status 'The newest release has no app package.'; return }
    if ([System.Windows.Forms.MessageBox]::Show("Update MeetDeck $cur to $latest?`nMeetDeck closes for a moment and starts again.",
            'MeetDeck', 'YesNo', 'Question') -ne 'Yes') { return }
    $tmp = Join-Path $env:TEMP "meetdeck-app-$latest.zip"
    Set-Status "Downloading $latest..."
    Invoke-WebRequest $asset.browser_download_url -OutFile $tmp -UseBasicParsing
    $new = Join-Path $Root 'app.new'
    if (Test-Path $new) { Remove-Item $new -Recurse -Force }
    Expand-Archive $tmp -DestinationPath $new -Force
    # the zip may hold the files at the top or inside an app\ folder
    $inner = Join-Path $new 'app'
    if ((Test-Path $inner) -and -not (Test-Path (Join-Path $new 'main.py'))) {
        $stage = Join-Path $Root 'app.new2'; Move-Item $inner $stage; Remove-Item $new -Recurse -Force; Move-Item $stage $new
    }
    $wasRunning = Test-Running
    Stop-MeetDeck
    if ($wasRunning) { Start-MeetDeck }      # start.py swaps app.new in on start
    Set-Status "Updated to $latest$(if (-not $wasRunning) { ' - it takes effect next time MeetDeck starts' })."
}

# ---------------------------------------------------------------- icon + shortcuts
# Own taskbar identity, so the window shows the MeetDeck icon instead of PowerShell's
try {
    Add-Type -Namespace MeetDeck -Name Shell -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("shell32.dll", SetLastError = true)]
public static extern int SetCurrentProcessExplicitAppUserModelID([System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.LPWStr)] string AppID);
'@
    [void][MeetDeck.Shell]::SetCurrentProcessExplicitAppUserModelID('bryanhadzik.meetdeck.launcher')
} catch { }

# "MeetDeck Launcher" shortcuts (desktop + Start menu) with the MeetDeck icon. The .cmd in the
# MeetDeck folder can't carry an icon, so this is what to double-click instead.
function Set-LauncherShortcuts {
    $ico = Join-Path $App 'static\meetdeck.ico'
    $ps1 = Join-Path $Here 'MeetDeck-Launcher.ps1'
    $folders = @([Environment]::GetFolderPath('Desktop'), (Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'Microsoft\Windows\Start Menu\Programs'))
    foreach ($dir in $folders) {
        try {
            if (-not (Test-Path $dir)) { continue }
            $sh = New-Object -ComObject WScript.Shell
            $lnk = $sh.CreateShortcut((Join-Path $dir 'MeetDeck Launcher.lnk'))
            $exe = Join-Path $Root 'MeetDeck Launcher.exe'
            if (Test-Path $exe) {
                $lnk.TargetPath = $exe; $lnk.Arguments = ''; $lnk.IconLocation = $exe + ',0'
            } else {
                $lnk.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
                $lnk.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $ps1 + '"'
                if (Test-Path $ico) { $lnk.IconLocation = $ico + ',0' }
            }
            $lnk.WorkingDirectory = $Root
            $lnk.Description = 'Start, stop and update MeetDeck'
            $lnk.Save()
        } catch { }
    }
}
Set-LauncherShortcuts

# ---------------------------------------------------------------- window
$f = New-Object Windows.Forms.Form
$f.Text = 'MeetDeck'; $f.StartPosition = 'CenterScreen'; $f.FormBorderStyle = 'FixedSingle'; $f.MaximizeBox = $false
$f.ClientSize = New-Object Drawing.Size(500, 506); $f.Font = New-Object Drawing.Font('Segoe UI', 9.5)
$ico = Join-Path $App 'static\meetdeck.ico'; if (Test-Path $ico) { $f.Icon = New-Object Drawing.Icon($ico) }

function Btn($text, $x, $y, $w, $parent, $click) {
    $b = New-Object Windows.Forms.Button; $b.Text = $text; $b.Location = New-Object Drawing.Point($x, $y)
    $b.Size = New-Object Drawing.Size($w, 30); $b.Add_Click($click); $parent.Controls.Add($b); $b
}
function Lbl($text, $x, $y, $w, $parent) {
    $l = New-Object Windows.Forms.Label; $l.Text = $text; $l.Location = New-Object Drawing.Point($x, $y)
    $l.Size = New-Object Drawing.Size($w, 20); $parent.Controls.Add($l); $l
}

# MeetDeck server
$g1 = New-Object Windows.Forms.GroupBox; $g1.Text = 'MeetDeck'; $g1.Location = New-Object Drawing.Point(12, 10); $g1.Size = New-Object Drawing.Size(476, 130); $f.Controls.Add($g1)
$state = Lbl '' 14 24 440 $g1; $state.Font = New-Object Drawing.Font('Segoe UI', 11, [Drawing.FontStyle]::Bold)
$null = Btn 'Start'  14 52 100 $g1 { Start-MeetDeck; Refresh-All }
$null = Btn 'Stop'  120 52 100 $g1 { Stop-MeetDeck; Set-Status 'MeetDeck stopped.'; Refresh-All }
$null = Btn 'Open in browser' 226 52 120 $g1 { Start-Process $Url }
$null = Btn 'Update' 352 52 108 $g1 { try { Update-MeetDeck } catch { Set-Status ('Update failed: ' + $_.Exception.Message) }; Refresh-All }
$null = Btn 'Data folder' 14 88 100 $g1 { Start-Process $Data }
$null = Btn 'Log' 120 88 100 $g1 { $l = Join-Path $Data 'meetdeck.log'; if (Test-Path $l) { Start-Process notepad.exe $l } }
$null = Btn 'Desktop shortcut' 226 88 120 $g1 {
    $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'MeetDeck Launcher.lnk'
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $s.TargetPath = 'powershell.exe'
    $s.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $Here 'MeetDeck-Launcher.ps1')`""
    $s.WorkingDirectory = $Root; if (Test-Path $ico) { $s.IconLocation = $ico }; $s.Description = 'MeetDeck launcher'; $s.Save()
    Set-Status 'Desktop shortcut made: MeetDeck Launcher.'
}

# CTS console tools
$g2 = New-Object Windows.Forms.GroupBox; $g2.Text = 'CTS console tools'; $g2.Location = New-Object Drawing.Point(12, 150); $g2.Size = New-Object Drawing.Size(476, 306); $f.Controls.Add($g2)
$null = Lbl 'Mode' 14 26 90 $g2
$mode = New-Object Windows.Forms.ComboBox; $mode.DropDownStyle = 'DropDownList'; $mode.Location = New-Object Drawing.Point(110, 22); $mode.Size = New-Object Drawing.Size(350, 24)
[void]$mode.Items.AddRange(@('Emulator - pretend to be the console', 'Tap - pass through to the real console and record', 'Listen only - record, never answer'))
$mode.SelectedIndex = 0; $g2.Controls.Add($mode)
$null = Lbl 'Port' 14 58 90 $g2
$port = New-Object Windows.Forms.ComboBox; $port.Location = New-Object Drawing.Point(110, 54); $port.Size = New-Object Drawing.Size(350, 24); $g2.Controls.Add($port)
$conLbl = Lbl 'Real console' 14 90 90 $g2
$conPort = New-Object Windows.Forms.ComboBox; $conPort.Location = New-Object Drawing.Point(110, 86); $conPort.Size = New-Object Drawing.Size(350, 24); $g2.Controls.Add($conPort)
$null = Lbl 'Parity' 14 122 90 $g2
$par = New-Object Windows.Forms.ComboBox; $par.DropDownStyle = 'DropDownList'; $par.Location = New-Object Drawing.Point(110, 118); $par.Size = New-Object Drawing.Size(60, 24)
[void]$par.Items.AddRange(@('N', 'E', 'O')); $par.SelectedIndex = 0; $g2.Controls.Add($par)
$prac = New-Object Windows.Forms.CheckBox; $prac.Text = 'Practice races (so "get times" has something to read)'; $prac.Checked = $true
$prac.Location = New-Object Drawing.Point(184, 120); $prac.Size = New-Object Drawing.Size(280, 22); $g2.Controls.Add($prac)
$hint = Lbl '' 14 148 446 $g2; $hint.Size = New-Object Drawing.Size(446, 36); $hint.ForeColor = [Drawing.Color]::DimGray
$toolState = Lbl '' 14 186 446 $g2; $toolState.Font = New-Object Drawing.Font('Segoe UI', 10, [Drawing.FontStyle]::Bold)

function Fill-Ports {
    $a = PortOf $port.Text; $b = PortOf $conPort.Text
    $list = @(Get-Ports)
    $port.Items.Clear(); $conPort.Items.Clear()
    foreach ($p in $list) { [void]$port.Items.Add($p); [void]$conPort.Items.Add($p) }
    if ($a) { $port.Text = ($list | Where-Object { (PortOf $_) -eq $a } | Select-Object -First 1) } 
    if ($b) { $conPort.Text = ($list | Where-Object { (PortOf $_) -eq $b } | Select-Object -First 1) }
}
$port.Add_DropDown({ Fill-Ports }); $conPort.Add_DropDown({ Fill-Ports })

function Update-ModeUi {
    $tap = $mode.SelectedIndex -eq 1
    $conLbl.Visible = $tap; $conPort.Visible = $tap; $prac.Enabled = ($mode.SelectedIndex -eq 0)
    $hint.Text = switch ($mode.SelectedIndex) {
        0 { 'Port = one end of the virtual pair or null-modem cable. Point Meet Manager (or MeetDeck) at the OTHER end.' }
        1 { 'Port = this end of the pair (Meet Manager uses the other end). Real console = the USB adapter plugged into the console.' }
        2 { 'Records everything that arrives on the port and never answers.' }
    }
}
$mode.Add_SelectedIndexChanged({ Update-ModeUi })

$null = Btn 'Start' 14 222 100 $g2 {
    if ((Get-ToolProcs).Count) { Set-Status 'A console tool is already running - stop it first.'; return }
    $p = PortOf $port.Text
    if (-not $p) { Set-Status 'Pick the port first.'; return }
    $cmd = @('-X', 'utf8', 'emulator.py', $p, '--parity', $par.Text)
    switch ($mode.SelectedIndex) {
        0 { if ($prac.Checked) { $cmd += '--practice' } }
        1 { $c = PortOf $conPort.Text; if (-not $c -or $c -eq $p) { Set-Status 'Pick the real console''s port (not the same port).'; return }; $cmd += @('--forward', $c) }
        2 { $cmd += '--listen-only' }
    }
    # its own console window, so every message shows as it happens
    $script:ToolProc = Start-Process -FilePath $Py -ArgumentList $cmd -WorkingDirectory $Timing -PassThru
    Set-Status ('Started: ' + ($cmd[2..($cmd.Count - 1)] -join ' ')); Refresh-All
}
$null = Btn 'Stop' 120 222 100 $g2 {
    foreach ($t in Get-ToolProcs) { try { Stop-Process -Id $t.ProcessId -Force } catch { } }
    Set-Status 'Console tool stopped. Its log and capture were saved as it ran.'; Refresh-All
}
$null = Btn 'Log' 226 222 100 $g2 { $l = Join-Path $TimingData 'emulator-log.txt'; if (Test-Path $l) { Start-Process notepad.exe $l } else { Set-Status 'No log yet.' } }
$null = Btn 'Capture files' 332 222 128 $g2 { New-Item -ItemType Directory -Force $TimingData | Out-Null; Start-Process explorer.exe $TimingData }
$null = Btn 'Compare last two runs' 14 258 200 $g2 {
    # e.g. run the emulator for Meet Manager's send, stop, start it again for MeetDeck's send, stop, then compare
    Start-Process -FilePath $Py -ArgumentList @('-X', 'utf8', 'emulator.py', '--compare') -WorkingDirectory $Timing
    Set-Status 'Comparing the two newest captures (also saved as emulator-compare.txt).'
}

# status line
$status = New-Object Windows.Forms.Label; $status.Location = New-Object Drawing.Point(14, 466); $status.Size = New-Object Drawing.Size(474, 34)
$status.ForeColor = [Drawing.Color]::DarkSlateGray; $f.Controls.Add($status)
function Set-Status($t) { $status.Text = $t; [System.Windows.Forms.Application]::DoEvents() }

function Refresh-All {
    $v = Get-Version
    if (Test-Running) { $state.Text = "Running  -  MeetDeck $v"; $state.ForeColor = [Drawing.Color]::ForestGreen }
    elseif ((Get-MeetDeckProcs).Count) { $state.Text = "Starting...  -  MeetDeck $v"; $state.ForeColor = [Drawing.Color]::DarkGoldenrod }
    else { $state.Text = "Stopped  -  MeetDeck $v"; $state.ForeColor = [Drawing.Color]::Firebrick }
    $t = @(Get-ToolProcs)
    if ($t.Count) {
        $cl = $t[0].CommandLine -replace '^.*emulator\.py\s*', ''
        $toolState.Text = "Running: $cl"; $toolState.ForeColor = [Drawing.Color]::ForestGreen
    } else { $toolState.Text = 'Not running'; $toolState.ForeColor = [Drawing.Color]::Firebrick }
}

$timer = New-Object Windows.Forms.Timer; $timer.Interval = 3000; $timer.Add_Tick({ Refresh-All }); $timer.Start()
$f.Add_Shown({ Fill-Ports; Update-ModeUi; Refresh-All; Set-Status "MeetDeck folder: $Root" })
[void]$f.ShowDialog()
