param(
    [Parameter(Mandatory=$true)][string]$Executable,
    [switch]$Required
)
$ErrorActionPreference = 'Stop'
$target = (Resolve-Path -LiteralPath $Executable).Path
if (-not $env:WINDOWS_SIGNING_PFX_BASE64 -or -not $env:WINDOWS_SIGNING_PASSWORD -or -not $env:WINDOWS_TIMESTAMP_URL) {
    if ($Required) { throw 'Release blocked: publisher signing certificate, password or timestamp URL missing.' }
    Write-Host 'Internal validation artifact: unsigned; not approved for customer distribution.'
    exit 0
}
# PowerShell's Authenticode timestamp API requires an HTTP endpoint.
if ($env:WINDOWS_TIMESTAMP_URL -notmatch '^http://') {
    throw 'Configure the certificate provider HTTP Authenticode timestamp endpoint.'
}
$temporaryCertificate = Join-Path ([IO.Path]::GetTempPath()) ("immo-signing-" + [Guid]::NewGuid().ToString('N') + '.pfx')
try {
    [IO.File]::WriteAllBytes($temporaryCertificate, [Convert]::FromBase64String($env:WINDOWS_SIGNING_PFX_BASE64))
    $password = ConvertTo-SecureString $env:WINDOWS_SIGNING_PASSWORD -AsPlainText -Force
    $certificate = Get-PfxCertificate -LiteralPath $temporaryCertificate -Password $password
    if (-not $certificate.HasPrivateKey) { throw 'Signing certificate has no private key.' }
    $signature = Set-AuthenticodeSignature -LiteralPath $target -Certificate $certificate -HashAlgorithm SHA256 -TimestampServer $env:WINDOWS_TIMESTAMP_URL
    $verified = Get-AuthenticodeSignature -LiteralPath $target
    if ($signature.Status -ne 'Valid' -or $verified.Status -ne 'Valid' -or -not $verified.TimeStamperCertificate) {
        throw "Release blocked: signature or timestamp validation failed ($($verified.Status))."
    }
    Write-Host "Verified publisher: $($verified.SignerCertificate.Subject)"
} finally {
    if ($certificate) { $certificate.Dispose() }
    Remove-Item -LiteralPath $temporaryCertificate -Force -ErrorAction SilentlyContinue
}
