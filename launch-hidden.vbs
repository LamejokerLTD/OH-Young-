Option Explicit

Dim shell, folder, command, fso, installCommand, quote
Set shell = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
Set fso = CreateObject("Scripting.FileSystemObject")
quote = Chr(34)

' First launch: install the private Python environment automatically.
If Not fso.FileExists(folder & "\.venv\Scripts\pythonw.exe") Then
    installCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & quote & folder & "\scripts\install.ps1" & quote
    shell.Run installCommand, 1, True
End If

If Not fso.FileExists(folder & "\.venv\Scripts\pythonw.exe") Then
    MsgBox "Installation incomplete. Run install.bat to retry.", 16, "Local Whisper"
    WScript.Quit 1
End If

command = quote & folder & "\.venv\Scripts\pythonw.exe" & quote & " " & quote & folder & "\launcher.py" & quote
shell.Run command, 0, False
