[CmdletBinding()]
param(
    [string]$ProjectName = "",
    [ValidateRange(320, 800)]
    [int]$Width = 420,
    [ValidateRange(420, 1200)]
    [int]$Height = 680,
    [ValidateRange(0, 100)]
    [int]$Margin = 12
)

$ErrorActionPreference = "Stop"
$encodedProject = [Uri]::EscapeDataString($ProjectName)
$Url = "http://127.0.0.1:8765/?compact=1"
if ($encodedProject) {
    $Url += "&project=$encodedProject"
}

$windowApi = @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class PampaPilotCompactWindow
{
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(
        IntPtr hWnd, IntPtr insertAfter, int x, int y, int width, int height, uint flags);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int command);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    public static IntPtr FindVisibleWindow(string titleFragment)
    {
        IntPtr match = IntPtr.Zero;
        EnumWindows(delegate(IntPtr window, IntPtr ignored)
        {
            if (!IsWindowVisible(window)) return true;
            var title = new StringBuilder(512);
            GetWindowText(window, title, title.Capacity);
            if (title.ToString().IndexOf(
                    titleFragment, StringComparison.OrdinalIgnoreCase) >= 0)
            {
                match = window;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return match;
    }
}
"@

Add-Type -TypeDefinition $windowApi
Add-Type -AssemblyName System.Windows.Forms

$browserCandidates = @(@(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) })

if (-not $browserCandidates) {
    throw "No se encontró Microsoft Edge ni Google Chrome"
}

$workingArea = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$actualWidth = [Math]::Min($Width, $workingArea.Width - (2 * $Margin))
$actualHeight = [Math]::Min($Height, $workingArea.Height - (2 * $Margin))
$x = $workingArea.Right - $actualWidth - $Margin
$y = $workingArea.Bottom - $actualHeight - $Margin
$title = if ($ProjectName) { "PampaPilot Compacto - $ProjectName" } else { "PampaPilot Compacto" }
$window = [PampaPilotCompactWindow]::FindVisibleWindow($title)

if ($window -eq [IntPtr]::Zero) {
    $arguments = @(
        "--app=$Url",
        "--new-window",
        "--window-size=$actualWidth,$actualHeight",
        "--window-position=$x,$y"
    )
    Start-Process -FilePath $browserCandidates[0] -ArgumentList $arguments | Out-Null

    $deadline = (Get-Date).AddSeconds(12)
    do {
        Start-Sleep -Milliseconds 150
        $window = [PampaPilotCompactWindow]::FindVisibleWindow($title)
    } while ($window -eq [IntPtr]::Zero -and (Get-Date) -lt $deadline)
}

if ($window -eq [IntPtr]::Zero) {
    throw "La ventana compacta no apareció dentro del tiempo esperado"
}

$topMost = [IntPtr](-1)
$showWindow = [uint32]0x0040
if (-not [PampaPilotCompactWindow]::SetWindowPos(
        $window, $topMost, $x, $y, $actualWidth, $actualHeight, $showWindow)) {
    throw "Windows no pudo fijar la ventana compacta"
}
[PampaPilotCompactWindow]::ShowWindow($window, 9) | Out-Null
[PampaPilotCompactWindow]::SetForegroundWindow($window) | Out-Null
