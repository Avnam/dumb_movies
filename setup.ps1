<#
  setup.ps1 - installs everything beat_movie.py needs on a Windows PC.

  Usage (from this folder, in PowerShell):
    .\setup.ps1            install what's missing, then check
    .\setup.ps1 -CheckOnly only check what's installed

  Versions used when the project was made (2026-11-17):
    Python 3.12.10, FFmpeg 9.0.2 (gyan.dev build), Git 2.56.0
    Python packages: see requirements.txt
#>
param([switch]$CheckOnly)

$tools = @(
    @{ Name = 'Python'; Id = 'Python.Python.3.12'; Version = '3.12.10';  Extra = @('--scope', 'user') },
    @{ Name = 'FFmpeg'; Id = 'Gyan.FFmpeg';        Version = '9.0.2';    Extra = @() },
    @{ Name = 'Git';    Id = 'Git.Git';            Version = '2.56.0.4'; Extra = @() }
)

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'Machine')
}

function Find-Python {
    $p = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (Test-Path $p) { return $p }
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c -and $c.Source -notmatch 'WindowsApps') { return $c.Source }
    return $null
}

if (-not $CheckOnly) {
    foreach ($t in $tools) {
        $installed = winget list --id $t.Id -e 2>$null | Select-String $t.Id
        if ($installed) { Write-Host "$($t.Name): already installed"; continue }
        Write-Host "Installing $($t.Name) $($t.Version)..."
        winget install --id $t.Id -e --version $t.Version --silent `
            --accept-package-agreements --accept-source-agreements @($t.Extra)
    }
    Refresh-Path
    $py = Find-Python
    if (-not $py) { throw 'Python was not found after installing it. Open a new PowerShell and run this again.' }
    & $py -m pip install --quiet -r (Join-Path $PSScriptRoot 'requirements.txt')
}

# ---- face models for grow_movie.py (OpenCV model zoo), verified by SHA-256
$models = @(
    @{ File = 'face_detection_yunet_2023mar.onnx'; Sha = '8F2383E4DD3CFBB4553EA8718107FC0423210DC964F9F4280604804ED2552FA4'
       Url  = 'https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx' },
    @{ File = 'face_recognition_sface_2021dec.onnx'; Sha = '0BA9FBFA01B5270C96627C4EF784DA859931E02F04419C829E83484087C34E79'
       Url  = 'https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx' }
)
$mdir = Join-Path $PSScriptRoot 'models'
foreach ($m in $models) {
    $f = Join-Path $mdir $m.File
    if (-not $CheckOnly -and -not (Test-Path $f)) {
        New-Item -ItemType Directory -Force $mdir | Out-Null
        Write-Host "Downloading $($m.File)..."
        curl.exe -sL -o $f $m.Url
    }
}

# ---- check
Refresh-Path
$ok = $true
$py = Find-Python
if ($py) { Write-Host ("Python : " + (& $py --version)) } else { Write-Host 'Python : MISSING'; $ok = $false }
foreach ($cmd in 'ffmpeg', 'ffprobe', 'git') {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $v = if ($cmd -eq 'git') { git --version } else { (& $cmd -version | Select-Object -First 1) -replace ' Copyright.*', '' }
        Write-Host ("{0,-7}: {1}" -f $cmd, $v)
    } else { Write-Host ("{0,-7}: MISSING" -f $cmd); $ok = $false }
}
if ($py) {
    $out = & $py -c 'import numpy, PIL; print(numpy.__version__, PIL.__version__)' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $v = "$out".Split(' ')
        Write-Host "Packages: numpy $($v[0]) | pillow $($v[1])"
    } else { Write-Host 'Packages: MISSING (run .\setup.ps1)'; $ok = $false }
}
foreach ($m in $models) {
    $f = Join-Path $mdir $m.File
    if (-not (Test-Path $f)) { Write-Host "Model  : $($m.File) MISSING"; $ok = $false }
    elseif ((Get-FileHash $f -Algorithm SHA256).Hash -ne $m.Sha) { Write-Host "Model  : $($m.File) WRONG CHECKSUM - delete it and run setup again"; $ok = $false }
    else { Write-Host "Model  : $($m.File) ok" }
}
if ($ok) { Write-Host 'All set.' } else { Write-Host 'Something is missing - see above.'; exit 1 }
