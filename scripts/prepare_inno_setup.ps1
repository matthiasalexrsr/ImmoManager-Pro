param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'

# The official compiler's own portable mode makes no installed-program entry,
# file association, or shortcut. Every build uses the verified immutable asset.
$version = '6.7.4'
$expectedHash = 'a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c'
$root = [IO.Path]::GetFullPath($OutputDirectory)
if ($root -eq [IO.Path]::GetPathRoot($root) -or $root.Contains('"')) {
    throw 'A dedicated build-tool directory is required.'
}
if ((Test-Path -LiteralPath $root) -and (Get-ChildItem -LiteralPath $root -Force | Select-Object -First 1)) {
    throw 'Compiler preparation requires a new or empty directory.'
}
New-Item -ItemType Directory -Path $root -Force | Out-Null
$download = Join-Path $root "innosetup-$version.exe"
Invoke-WebRequest -Uri "https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-$version.exe" -OutFile $download
if ((Get-Item -LiteralPath $download).Length -ne 10604576 -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $download).Hash.ToLowerInvariant() -ne $expectedHash) {
    throw 'Inno Setup source asset does not match the pinned official digest.'
}
$signature = Get-AuthenticodeSignature -LiteralPath $download
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(^|, )O=Pyrsys B\.V\.(,|$)') {
    throw 'The compiler download does not have the expected valid publisher signature.'
}
$compilerDir = Join-Path $root 'compiler'
$process = Start-Process -FilePath $download -ArgumentList (
    '/PORTABLE=1 /CURRENTUSER /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /DIR="' + $compilerDir + '"'
) -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Portable compiler preparation failed: $($process.ExitCode)" }
$iscc = Join-Path $compilerDir 'ISCC.exe'
if (-not (Test-Path -LiteralPath $iscc -PathType Leaf)) { throw 'The prepared compiler is missing.' }
[ordered]@{
    version = $version
    source = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-$version.exe"
    sha256 = $expectedHash
    publisher = $signature.SignerCertificate.Subject
    signature = [string]$signature.Status
    portable = $true
    compiler = $iscc
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'compiler-provenance.json') -Encoding utf8
if ($env:GITHUB_OUTPUT) { "iscc=$iscc" >> $env:GITHUB_OUTPUT }
Write-Host "Verified portable Inno Setup $version is ready."
