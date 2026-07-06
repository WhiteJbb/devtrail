' run-hidden.vbs - PowerShell 스크립트를 콘솔 창 없이 실행
' powershell.exe -WindowStyle Hidden은 콘솔 창이 생성된 뒤 숨기므로 깜빡임이 남는다.
' WshShell.Run(cmd, 0)은 SW_HIDE로 프로세스를 만들어 창이 아예 뜨지 않는다.
' 사용: wscript.exe //B //Nologo run-hidden.vbs <ps1 경로> [추가 인자...]
Dim args, cmd, i, rc
Set args = WScript.Arguments
If args.Count < 1 Then WScript.Quit 1

cmd = "powershell.exe -NonInteractive -ExecutionPolicy Bypass -File """ & args(0) & """"
For i = 1 To args.Count - 1
    cmd = cmd & " " & args(i)
Next

rc = CreateObject("WScript.Shell").Run(cmd, 0, True)
WScript.Quit rc
