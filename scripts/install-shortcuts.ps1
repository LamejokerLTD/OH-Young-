param([string]$DestinationDirectory)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$launcher = Join-Path $projectRoot 'launch-hidden.vbs'
$legacyLauncher = Join-Path $projectRoot 'start.bat'
$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$wscriptArguments = '"' + $launcher + '"'
if (-not (Test-Path (Join-Path $projectRoot '.venv\Scripts\python.exe'))) {
    throw 'Please run install.bat first, then install shortcuts again.'
}

function Test-OurShortcut {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $existing = $shell.CreateShortcut($Path)
    if ($existing.TargetPath -eq $legacyLauncher) { return $true }
    if ($existing.TargetPath -eq $launcher) { return $true }
    if ($existing.TargetPath -eq $wscript -and $existing.Arguments -eq $wscriptArguments) { return $true }
    return $false
}

$shortcutName = 'Local Whisper.lnk'
$destinations = if ($DestinationDirectory) {
    @($DestinationDirectory)
} else {
    @([Environment]::GetFolderPath('DesktopDirectory'),
      [Environment]::GetFolderPath('Programs'))
}
$shell = New-Object -ComObject WScript.Shell
foreach ($destination in $destinations) {
    if (-not $destination -or -not (Test-Path -LiteralPath $destination -PathType Container)) {
        throw "Shortcut destination does not exist: $destination"
    }
    $shortcutPath = Join-Path $destination $shortcutName
    if ((Test-Path -LiteralPath $shortcutPath) -and -not (Test-OurShortcut -Path $shortcutPath)) {
        $folderName = Split-Path $projectRoot -Leaf
        $shortcutPath = $null
        for ($index = 0; $index -lt 100; $index++) {
            $suffix = if ($index -eq 0) { '' } else { " $index" }
            $candidatePath = Join-Path $destination "Local Whisper ($folderName)$suffix.lnk"
            if (-not (Test-Path -LiteralPath $candidatePath) -or (Test-OurShortcut -Path $candidatePath)) {
                $shortcutPath = $candidatePath
                break
            }
        }
        if (-not $shortcutPath) { throw "No available shortcut name in: $destination" }
    }
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $wscript
    $shortcut.Arguments = $wscriptArguments
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.WindowStyle = 1
    $shortcut.Description = 'Local Whisper transcription tool'
    $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,0"
    $shortcut.Save()
    Write-Host "Created: $shortcutPath"
}
Write-Host 'Done. Open Local Whisper from your desktop or Start menu; it starts without a terminal window.' -ForegroundColor Green
