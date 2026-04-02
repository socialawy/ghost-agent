# ghost-inject.ps1 — Quick inject from anywhere in E:\co
# Usage: ghost-inject "GRID just passed 900 tests"
# Usage: ghost-inject -f .\some-file.md

param(
    [Parameter(Position=0, ValueFromRemainingArguments=$true)]
    [string[]]$Text,
    
    [Alias("f")]
    [string]$File
)

$ghostDir = "E:\co\ghost-agent"
$venv = "$ghostDir\.venv\Scripts\python.exe"

Push-Location $ghostDir
try {
    if ($File) {
        & $venv ghost.py inject -f $File
    } elseif ($Text) {
        $joined = $Text -join " "
        & $venv ghost.py inject $joined
    } else {
        Write-Host "Usage: ghost-inject 'your observation here'" -ForegroundColor Yellow
        Write-Host "       ghost-inject -f path\to\file.md" -ForegroundColor Yellow
    }
} finally {
    Pop-Location
}