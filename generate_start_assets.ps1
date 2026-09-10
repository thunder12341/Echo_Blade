$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$root = Join-Path (Get-Location) 'images'
New-Item -ItemType Directory -Force -Path $root | Out-Null

function C([int]$r, [int]$g, [int]$b, [int]$a = 255) {
    return [System.Drawing.Color]::FromArgb($a, $r, $g, $b)
}

function Save-Png($bitmap, [string]$name) {
    $path = Join-Path $root $name
    $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()
    Write-Output $path
}

function New-PixelCanvas([int]$w, [int]$h) {
    $bitmap = New-Object System.Drawing.Bitmap $w, $h, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $bitmap.SetResolution(96, 96)
    return $bitmap
}

function Scale-PixelArt($source, [int]$scale, [string]$name) {
    $target = New-PixelCanvas ($source.Width * $scale) ($source.Height * $scale)
    $g = [System.Drawing.Graphics]::FromImage($target)
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
    $g.DrawImage($source, 0, 0, $target.Width, $target.Height)
    $g.Dispose()
    $source.Dispose()
    Save-Png $target $name
}

# 1) Main menu background: a 320x180 pixel scene scaled to 1280x720.
$bg = New-PixelCanvas 320 180
$g = [System.Drawing.Graphics]::FromImage($bg)
$g.Clear((C 7 12 25))

# Layered night sky bands.
for ($y = 0; $y -lt 112; $y++) {
    $t = $y / 112.0
    $r = [int](10 + 12 * $t)
    $b = [int](29 + 35 * $t)
    $g.DrawLine((New-Object System.Drawing.Pen (C $r 20 $b)), 0, $y, 319, $y)
}

# Pixel stars and a broken moon.
$starBrush = New-Object System.Drawing.SolidBrush (C 129 212 223)
$dimStar = New-Object System.Drawing.SolidBrush (C 57 117 145)
foreach ($p in @(@(18,18), @(42,30), @(79,15), @(112,42), @(151,21), @(188,33), @(225,17), @(279,28), @(304,49), @(25,74), @(91,66), @(247,71))) {
    $size = if (($p[0] + $p[1]) % 3 -eq 0) { 2 } else { 1 }
    $g.FillRectangle($starBrush, $p[0], $p[1], $size, $size)
}
foreach ($p in @(@(55,54), @(133,12), @(171,56), @(212,49), @(294,15), @(14,49))) {
    $g.FillRectangle($dimStar, $p[0], $p[1], 1, 1)
}

$moon = New-Object System.Drawing.SolidBrush (C 220 242 213)
$moonShadow = New-Object System.Drawing.SolidBrush (C 105 178 186)
$g.FillRectangle($moon, 252, 29, 25, 3)
$g.FillRectangle($moon, 247, 32, 32, 20)
$g.FillRectangle($moon, 252, 52, 25, 4)
$g.FillRectangle($moonShadow, 257, 34, 19, 16)
$g.FillRectangle((New-Object System.Drawing.SolidBrush (C 10 22 39)), 268, 31, 12, 22)

# Far skyline.
$far = New-Object System.Drawing.SolidBrush (C 17 37 55)
foreach ($b in @(@(0,106,26,74), @(25,92,18,88), @(44,116,22,64), @(68,84,27,96), @(98,104,18,76), @(118,73,28,107), @(150,99,20,81), @(172,78,25,102), @(202,108,29,72), @(238,86,18,94), @(260,102,24,78), @(286,76,34,104))) {
    $g.FillRectangle($far, $b[0], $b[1], $b[2], $b[3])
}
$window = New-Object System.Drawing.SolidBrush (C 47 119 126)
foreach ($p in @(@(8,118), @(13,129), @(34,105), @(73,99), @(82,117), @(126,86), @(132,102), @(180,91), @(191,121), @(249,99), @(269,119), @(301,96))) {
    $g.FillRectangle($window, $p[0], $p[1], 2, 3)
}

# Near skyline and central gate, leaving negative space for the title/menu.
$near = New-Object System.Drawing.SolidBrush (C 11 24 38)
foreach ($b in @(@(0,128,33,52), @(31,119,18,61), @(49,135,29,45), @(79,111,21,69), @(101,127,31,53), @(132,116,19,64), @(151,133,30,47), @(183,109,23,71), @(208,126,36,54), @(244,118,24,62), @(270,132,20,48), @(291,112,29,68))) {
    $g.FillRectangle($near, $b[0], $b[1], $b[2], $b[3])
}

$gate = New-Object System.Drawing.SolidBrush (C 20 49 61)
$gateGlow = New-Object System.Drawing.SolidBrush (C 45 145 153)
$g.FillRectangle($gate, 136, 102, 48, 78)
$g.FillRectangle($gate, 128, 116, 64, 64)
$g.FillRectangle($gateGlow, 143, 111, 34, 69)
$g.FillRectangle((New-Object System.Drawing.SolidBrush (C 8 21 33)), 148, 126, 24, 54)
$g.FillRectangle((New-Object System.Drawing.SolidBrush (C 107 224 207)), 144, 108, 32, 3)
$g.FillRectangle((New-Object System.Drawing.SolidBrush (C 20 78 88)), 126, 119, 4, 61)
$g.FillRectangle((New-Object System.Drawing.SolidBrush (C 20 78 88)), 190, 119, 4, 61)

# Foreground platform and cyan echo fragments.
$ground = New-Object System.Drawing.SolidBrush (C 8 16 28)
$g.FillRectangle($ground, 0, 160, 320, 20)
$g.FillRectangle((New-Object System.Drawing.SolidBrush (C 26 74 79)), 0, 160, 320, 2)
$echo = New-Object System.Drawing.SolidBrush (C 79 220 214)
foreach ($p in @(@(46,151), @(53,145), @(61,154), @(236,150), @(244,143), @(252,153))) {
    $g.FillRectangle($echo, $p[0], $p[1], 2, 5)
    $g.FillRectangle($echo, $p[0] + 2, $p[1] + 2, 2, 2)
}

$g.Dispose()
Scale-PixelArt $bg 4 'title_background.png'

# 2) Transparent logo emblem: a faceted echo blade rune.
$logo = New-PixelCanvas 64 64
$lg = [System.Drawing.Graphics]::FromImage($logo)
$lg.Clear([System.Drawing.Color]::Transparent)
$dark = New-Object System.Drawing.SolidBrush (C 10 21 35 240)
$cyan = New-Object System.Drawing.SolidBrush (C 79 220 214 255)
$light = New-Object System.Drawing.SolidBrush (C 211 255 232 255)
$red = New-Object System.Drawing.SolidBrush (C 239 102 105 255)
$lg.FillPolygon($dark, @([System.Drawing.Point]::new(31, 2), [System.Drawing.Point]::new(56, 27), [System.Drawing.Point]::new(37, 61), [System.Drawing.Point]::new(8, 43)))
$lg.FillPolygon($cyan, @([System.Drawing.Point]::new(31, 7), [System.Drawing.Point]::new(49, 27), [System.Drawing.Point]::new(35, 52), [System.Drawing.Point]::new(19, 38)))
$lg.FillPolygon($light, @([System.Drawing.Point]::new(31, 8), [System.Drawing.Point]::new(36, 28), [System.Drawing.Point]::new(28, 37), [System.Drawing.Point]::new(23, 31)))
$lg.FillRectangle($red, 30, 27, 5, 15)
$lg.FillRectangle($light, 20, 42, 26, 3)
$lg.Dispose()
Scale-PixelArt $logo 4 'logo_emblem.png'

# 3) Player idle sprite, transparent and ready for layered menu composition.
$player = New-PixelCanvas 32 40
$pg = [System.Drawing.Graphics]::FromImage($player)
$pg.Clear([System.Drawing.Color]::Transparent)
$outline = New-Object System.Drawing.SolidBrush (C 5 11 22 255)
$coat = New-Object System.Drawing.SolidBrush (C 39 77 94 255)
$coatHi = New-Object System.Drawing.SolidBrush (C 75 160 158 255)
$skin = New-Object System.Drawing.SolidBrush (C 246 185 133 255)
$blade = New-Object System.Drawing.SolidBrush (C 215 250 224 255)
$accent = New-Object System.Drawing.SolidBrush (C 239 102 105 255)
$pg.FillRectangle($outline, 12, 5, 10, 10)
$pg.FillRectangle($skin, 14, 7, 7, 7)
$pg.FillRectangle($outline, 9, 14, 15, 16)
$pg.FillRectangle($coat, 11, 16, 11, 13)
$pg.FillRectangle($coatHi, 12, 16, 4, 9)
$pg.FillRectangle($accent, 18, 17, 4, 3)
$pg.FillRectangle($outline, 10, 29, 6, 9)
$pg.FillRectangle($outline, 18, 29, 6, 9)
$pg.FillRectangle($coatHi, 11, 29, 4, 7)
$pg.FillRectangle($coat, 19, 29, 4, 7)
$pg.FillRectangle($outline, 23, 15, 3, 14)
$pg.FillRectangle($blade, 25, 7, 3, 20)
$pg.FillRectangle($blade, 28, 5, 2, 4)
$pg.FillRectangle($accent, 24, 26, 5, 3)
$pg.Dispose()
Scale-PixelArt $player 3 'player_idle.png'

# 4) Transparent menu panel with a crisp pixel frame.
$panel = New-PixelCanvas 160 32
$pn = [System.Drawing.Graphics]::FromImage($panel)
$pn.Clear([System.Drawing.Color]::Transparent)
$panelFill = New-Object System.Drawing.SolidBrush (C 6 16 28 218)
$panelEdge = New-Object System.Drawing.SolidBrush (C 62 142 151 255)
$panelHi = New-Object System.Drawing.SolidBrush (C 120 235 215 255)
$pn.FillRectangle($panelFill, 2, 2, 156, 28)
$pn.FillRectangle($panelEdge, 0, 4, 2, 24)
$pn.FillRectangle($panelEdge, 158, 4, 2, 24)
$pn.FillRectangle($panelEdge, 4, 0, 152, 2)
$pn.FillRectangle($panelEdge, 4, 30, 152, 2)
$pn.FillRectangle($panelHi, 8, 3, 22, 1)
$pn.FillRectangle($panelHi, 130, 28, 22, 1)
$pn.Dispose()
Scale-PixelArt $panel 4 'menu_panel.png'

# 5) Menu cursor shaped like a tiny reflected blade.
$cursor = New-PixelCanvas 16 16
$cu = [System.Drawing.Graphics]::FromImage($cursor)
$cu.Clear([System.Drawing.Color]::Transparent)
$cu.FillPolygon((New-Object System.Drawing.SolidBrush (C 211 255 232)), @([System.Drawing.Point]::new(1, 8), [System.Drawing.Point]::new(12, 2), [System.Drawing.Point]::new(8, 8), [System.Drawing.Point]::new(12, 14)))
$cu.FillRectangle((New-Object System.Drawing.SolidBrush (C 239 102 105)), 2, 7, 4, 3)
$cu.Dispose()
Scale-PixelArt $cursor 3 'menu_cursor.png'

# 6) Parry flash used by the title screen's ambient animation or tutorial preview.
$spark = New-PixelCanvas 32 32
$sp = [System.Drawing.Graphics]::FromImage($spark)
$sp.Clear([System.Drawing.Color]::Transparent)
$sparkBrush = New-Object System.Drawing.SolidBrush (C 211 255 232)
$sparkCyan = New-Object System.Drawing.SolidBrush (C 79 220 214)
$sp.FillRectangle($sparkBrush, 15, 2, 2, 10)
$sp.FillRectangle($sparkBrush, 15, 20, 2, 10)
$sp.FillRectangle($sparkBrush, 2, 15, 10, 2)
$sp.FillRectangle($sparkBrush, 20, 15, 10, 2)
$sp.FillRectangle($sparkCyan, 8, 8, 4, 4)
$sp.FillRectangle($sparkCyan, 20, 8, 4, 4)
$sp.FillRectangle($sparkCyan, 8, 20, 4, 4)
$sp.FillRectangle($sparkCyan, 20, 20, 4, 4)
$sp.FillRectangle($sparkBrush, 14, 14, 4, 4)
$sp.Dispose()
Scale-PixelArt $spark 4 'parry_spark.png'

Write-Output 'Generated start screen assets.'
