$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        $candidates = @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", 'python.exe', 'py.exe')
        $pythonPath = $null
        foreach ($candidate in $candidates) {
            $command = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($command) {
                try {
                    & $command.Source -c 'import sys, struct; sys.exit(0 if sys.version_info[:2] == (3, 12) and struct.calcsize("P") == 8 else 1)' 2>$null
                    if ($LASTEXITCODE -eq 0) { $pythonPath = $command.Source; break }
                } catch {
                    Write-Host "Skipping unusable Python candidate: $candidate" -ForegroundColor Yellow
                }
            }
        }
        if (-not $pythonPath) {
            Write-Host 'Installing Python 3.12 from python.org...'
            $installer = Join-Path $env:TEMP 'whisper-python-3.12.10.exe'
            Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $installer
            $signature = Get-AuthenticodeSignature $installer
            if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*Python Software Foundation*') { throw 'Python installer signature verification failed.' }
            $process = Start-Process -FilePath $installer -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_test=0' -WindowStyle Hidden -Wait -PassThru
            if ($process.ExitCode -ne 0) { throw 'Python installation failed.' }
            $pythonPath = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
        }
        & $pythonPath -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' }
    }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your Internet connection.' }
    & '.\.venv\Scripts\python.exe' -m app.diagnostics
    if ($LASTEXITCODE -ne 0) { throw 'Dependency checks failed.' }
    & (Join-Path $PSScriptRoot 'install-shortcuts.ps1')
    Write-Host 'Installation complete. Local Whisper shortcuts have been placed on your desktop and in the Start menu.' -ForegroundColor Green
    Write-Host 'Double-click the desktop shortcut to start it without a terminal window.'
    Write-Host 'Large-v3 downloads automatically on first transcription if not cached.'
} catch {
    Write-Host "`nInstallation error:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    if ($_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace -ForegroundColor DarkRed }
    Write-Host "`nThe full installer window will remain open so the error can be read." -ForegroundColor Yellow
    exit 1
}
