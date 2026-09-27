$ErrorActionPreference = 'Stop'
$qsRoot = Split-Path -Parent $PSScriptRoot
$qsWord = New-Object -ComObject Word.Application
$qsDoc = $null
$qsInitialDocuments = $qsWord.Documents.Count
try {
    $qsWord.Visible = $false
    $qsWord.DisplayAlerts = 0
    $qsInput = Join-Path $qsRoot 'docs\QuantScore_V1.4_机器可执行评分规则规范_真实数据接入版.docx'
    $qsOutput = Join-Path $qsRoot 'outputs\v14_render\spec-v14.pdf'
    New-Item -ItemType Directory -Path (Split-Path -Parent $qsOutput) -Force | Out-Null
    $qsDoc = $qsWord.Documents.Open($qsInput, $false, $true)
    $qsDoc.ExportAsFixedFormat($qsOutput, 17)
    Write-Output ('Exported PDF; pages=' + $qsDoc.ComputeStatistics(2))
} finally {
    if ($null -ne $qsDoc) {
        $qsDoc.Close(0)
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($qsDoc)
    }
    if ($qsInitialDocuments -eq 0 -and $qsWord.Documents.Count -eq 0) { $qsWord.Quit() }
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($qsWord)
}
