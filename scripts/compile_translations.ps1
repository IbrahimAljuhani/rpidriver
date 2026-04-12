# RPiDriver — Compile .po translation files to .mo binary format.
# No Python or pybabel required — uses pure .NET System.IO.
#
# Usage (from project root):
#   powershell -ExecutionPolicy Bypass -File scripts\compile_translations.ps1

$ErrorActionPreference = 'Stop'

$TranslationsDir = Resolve-Path (Join-Path $PSScriptRoot '..\rpidriver\translations')

# ── PO parser ─────────────────────────────────────────────────────────────────

function Get-PoEntries([string]$Path) {
    $enc   = [System.Text.Encoding]::UTF8
    $lines = [System.IO.File]::ReadAllLines($Path, $enc)

    $entries = [System.Collections.Generic.List[pscustomobject]]::new()
    $msgid   = $null
    $msgstr  = $null
    $state   = ''

    foreach ($line in $lines) {
        if ($line.StartsWith('#')) { continue }

        if ($line -match '^msgid "(.*)"') {
            # Flush previous entry
            if ($null -ne $msgid) {
                $entries.Add([pscustomobject]@{ Id = $msgid; Str = ([string]$msgstr) })
            }
            $msgid  = $Matches[1]
            $msgstr = $null
            $state  = 'id'
        }
        elseif ($line -match '^msgstr "(.*)"') {
            $msgstr = $Matches[1]
            $state  = 'str'
        }
        elseif ($line -match '^"(.*)"') {
            if ($state -eq 'id')  { $msgid  += $Matches[1] }
            if ($state -eq 'str') { $msgstr += $Matches[1] }
        }
    }
    # Flush last entry
    if ($null -ne $msgid) {
        $entries.Add([pscustomobject]@{ Id = $msgid; Str = ([string]$msgstr) })
    }

    # .mo requires entries sorted by original string in binary order
    return @($entries | Sort-Object { $_.Id })
}

# ── Unescape PO string escapes ────────────────────────────────────────────────

function Unescape-Po([string]$s) {
    return $s -replace '\\n', "`n" `
              -replace '\\t', "`t" `
              -replace '\\"', '"'
}

# ── MO writer ─────────────────────────────────────────────────────────────────

function Write-Mo([string]$PoPath, [string]$MoPath) {
    $enc     = [System.Text.Encoding]::UTF8
    $entries = Get-PoEntries $PoPath
    $N       = $entries.Count

    # Encode strings
    $origBytes  = [byte[][]]::new($N)
    $transBytes = [byte[][]]::new($N)

    for ($i = 0; $i -lt $N; $i++) {
        $origBytes[$i]  = $enc.GetBytes((Unescape-Po $entries[$i].Id))
        $transBytes[$i] = $enc.GetBytes((Unescape-Po $entries[$i].Str))
    }

    # Offset layout:
    #   [0..27]            header  (7 × uint32)
    #   [28..28+N*8-1]     original strings table  (N × {len, offset})
    #   [28+N*8..28+2N*8-1] translated strings table (N × {len, offset})
    #   [28+2N*8..]        string data (originals then translations, each null-terminated)

    $origTableOff  = 28
    $transTableOff = $origTableOff  + $N * 8
    $stringsStart  = $transTableOff + $N * 8

    $origOff  = [int[]]::new($N)
    $transOff = [int[]]::new($N)

    $pos = $stringsStart
    for ($i = 0; $i -lt $N; $i++) { $origOff[$i]  = $pos; $pos += $origBytes[$i].Length  + 1 }
    for ($i = 0; $i -lt $N; $i++) { $transOff[$i] = $pos; $pos += $transBytes[$i].Length + 1 }

    # Helper: write uint32 little-endian (avoids PowerShell uint32 cast issues)
    $writeU32 = {
        param([System.IO.BinaryWriter]$w, [int64]$v)
        $w.Write([byte]( $v         -band 0xFF))
        $w.Write([byte](($v -shr 8) -band 0xFF))
        $w.Write([byte](($v -shr 16) -band 0xFF))
        $w.Write([byte](($v -shr 24) -band 0xFF))
    }

    # Write binary MO
    $ms = [System.IO.MemoryStream]::new()
    $bw = [System.IO.BinaryWriter]::new($ms)

    # Header
    & $writeU32 $bw 0x950412de    # magic number (little-endian)
    & $writeU32 $bw 0              # file format revision
    & $writeU32 $bw $N             # number of strings
    & $writeU32 $bw $origTableOff  # offset of original strings table
    & $writeU32 $bw $transTableOff # offset of translated strings table
    & $writeU32 $bw 0              # hash table size (not used)
    & $writeU32 $bw 0              # hash table offset (not used)

    # Original strings table
    for ($i = 0; $i -lt $N; $i++) {
        & $writeU32 $bw $origBytes[$i].Length
        & $writeU32 $bw $origOff[$i]
    }

    # Translated strings table
    for ($i = 0; $i -lt $N; $i++) {
        & $writeU32 $bw $transBytes[$i].Length
        & $writeU32 $bw $transOff[$i]
    }

    # String data — originals
    foreach ($b in $origBytes)  { $bw.Write($b); $bw.Write([byte]0) }
    # String data — translations
    foreach ($b in $transBytes) { $bw.Write($b); $bw.Write([byte]0) }

    $bw.Flush()
    [System.IO.File]::WriteAllBytes($MoPath, $ms.ToArray())
    $bw.Dispose()
    $ms.Dispose()

    $locale = Split-Path (Split-Path $PoPath -Parent) -Leaf
    Write-Host "  [OK] $locale — $N strings — $MoPath"
}

# ── Main ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "RPiDriver: Compiling translation catalogs"
Write-Host "  Source: $TranslationsDir"
Write-Host ""

$poFiles = Get-ChildItem -Path $TranslationsDir -Filter 'messages.po' -Recurse

if ($poFiles.Count -eq 0) {
    Write-Host "  [!] No messages.po files found."
    exit 1
}

foreach ($po in $poFiles) {
    $mo = Join-Path $po.DirectoryName 'messages.mo'
    Write-Mo -PoPath $po.FullName -MoPath $mo
}

Write-Host ""
Write-Host "Done. Add the generated .mo files to git:"
Write-Host "  git add rpidriver/translations"
Write-Host ""
