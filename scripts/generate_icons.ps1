<#
.SYNOPSIS
    Generates icon-192.png and icon-512.png using .NET System.Drawing.
    No Python, no Pillow, no external tools required.

.USAGE
    From the project root in PowerShell:
        .\scripts\generate_icons.ps1
#>

Add-Type -AssemblyName System.Drawing

$OutDir = Join-Path $PSScriptRoot "..\html\icons"
$OutDir = [System.IO.Path]::GetFullPath($OutDir)

# ── Colour palette ────────────────────────────────────────────────────────────
$BG    = [System.Drawing.Color]::FromArgb(255,  10,  15,  30)   # #0a0f1e
$BLUE  = [System.Drawing.Color]::FromArgb(255,  99, 179, 237)   # #63b3ed
$GREEN = [System.Drawing.Color]::FromArgb(255,  72, 187, 120)   # #48bb78

function New-Icon {
    param([int]$Size)

    $bmp  = New-Object System.Drawing.Bitmap($Size, $Size)
    $g    = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode    = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit

    # ── Background rounded rect ───────────────────────────────────────────
    $radius = [int]($Size * 96 / 512)
    $bgBrush = New-Object System.Drawing.SolidBrush($BG)
    Add-RoundedRect $g $bgBrush 0 0 $Size $Size $radius

    # ── Border ───────────────────────────────────────────────────────────
    $border  = [Math]::Max(2, [int]($Size * 8 / 512))
    $margin  = [int]($Size * 32 / 512)
    $bRadius = [Math]::Max(2, [int]($Size * 72 / 512))
    $pen     = New-Object System.Drawing.Pen($BLUE, $border)
    Add-RoundedRectOutline $g $pen $margin $margin ($Size - $margin * 2) ($Size - $margin * 2) $bRadius

    # ── "Pi" text ─────────────────────────────────────────────────────────
    $piPts  = [int]($Size * 118 / 512)   # ~156px at 512 in graphics units
    $drvPts = [int]($Size *  30 / 512)   # ~40px  at 512

    $fontPi  = New-Object System.Drawing.Font("Courier New", $piPts,  [System.Drawing.FontStyle]::Bold)
    $fontDrv = New-Object System.Drawing.Font("Courier New", $drvPts, [System.Drawing.FontStyle]::Regular)

    $brushBlue  = New-Object System.Drawing.SolidBrush($BLUE)
    $brushGreen = New-Object System.Drawing.SolidBrush($GREEN)

    $fmt = New-Object System.Drawing.StringFormat
    $fmt.Alignment     = [System.Drawing.StringAlignment]::Center
    $fmt.LineAlignment = [System.Drawing.StringAlignment]::Center

    $piY  = [int]($Size * 255 / 512)
    $drvY = [int]($Size * 360 / 512)

    $piRect  = New-Object System.Drawing.RectangleF(0, ($piY  - $piPts  * 0.6), $Size, ($piPts  * 1.4))
    $drvRect = New-Object System.Drawing.RectangleF(0, ($drvY - $drvPts * 0.6), $Size, ($drvPts * 1.4))

    $g.DrawString("Pi",     $fontPi,  $brushBlue,  $piRect,  $fmt)
    $g.DrawString("Driver", $fontDrv, $brushGreen, $drvRect, $fmt)

    # cleanup
    $g.Dispose()
    $fontPi.Dispose(); $fontDrv.Dispose()
    $bgBrush.Dispose(); $brushBlue.Dispose(); $brushGreen.Dispose()
    $pen.Dispose()

    return $bmp
}

# Rounded rectangle fill helper
function Add-RoundedRect {
    param($g, $brush, $x, $y, $w, $h, $r)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc($x,           $y,           $r*2, $r*2, 180, 90)
    $path.AddArc($x+$w-$r*2,  $y,           $r*2, $r*2, 270, 90)
    $path.AddArc($x+$w-$r*2,  $y+$h-$r*2,  $r*2, $r*2,   0, 90)
    $path.AddArc($x,           $y+$h-$r*2,  $r*2, $r*2,  90, 90)
    $path.CloseFigure()
    $g.FillPath($brush, $path)
    $path.Dispose()
}

# Rounded rectangle outline helper
function Add-RoundedRectOutline {
    param($g, $pen, $x, $y, $w, $h, $r)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc($x,           $y,           $r*2, $r*2, 180, 90)
    $path.AddArc($x+$w-$r*2,  $y,           $r*2, $r*2, 270, 90)
    $path.AddArc($x+$w-$r*2,  $y+$h-$r*2,  $r*2, $r*2,   0, 90)
    $path.AddArc($x,           $y+$h-$r*2,  $r*2, $r*2,  90, 90)
    $path.CloseFigure()
    $g.DrawPath($pen, $path)
    $path.Dispose()
}

# ── Generate both sizes ───────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

foreach ($sz in 192, 512) {
    $bmp = New-Icon -Size $sz
    $out = Join-Path $OutDir "icon-$sz.png"
    $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Host "  Saved $out  ($sz x $sz)"
}

Write-Host "Done."
