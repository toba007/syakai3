param(
    [string]$Output = "news_speech.txt",
    [int]$RefreshLimit = 100,
    [int]$RefreshInterval = 10,
    [switch]$Watch,
    [string]$NewsApiKey = $env:NEWS_API_KEY,
    [string]$DbPath = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptPath = Join-Path $PSScriptRoot "fetch_japan_news.py"

$pythonCandidates = @(
    (Join-Path $PSScriptRoot "..\python311\python.exe"),
    "py",
    "python"
)
$python = $null
foreach ($candidate in $pythonCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        $python = $candidate
        break
    }
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $python = $candidate
        break
    }
}

if (-not $python) {
    throw "Python interpreter was not found."
}

$argsList = @(
    $scriptPath,
    "--output", $Output,
    "--refresh-limit", $RefreshLimit.ToString()
)

if ($Watch) {
    $argsList += "--watch"
    $argsList += @("--refresh-interval", $RefreshInterval.ToString())
}

if ($NewsApiKey) {
    $argsList += @("--news-api-key", $NewsApiKey)
}

if ($DbPath) {
    $argsList += @("--db-path", $DbPath)
}

& $python @argsList
exit $LASTEXITCODE
