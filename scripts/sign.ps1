param([Parameter(Mandatory=$true)][string]$File)
$ErrorActionPreference = 'Stop'
if (-not $env:SIGNING_PFX_BASE64 -or -not $env:SIGNING_PFX_PASSWORD) {
    throw 'Configure both signing secrets before running the signing stage.'
}
$pfxPath = Join-Path $env:RUNNER_TEMP 'titlevision-signing.pfx'
try {
    [IO.File]::WriteAllBytes($pfxPath, [Convert]::FromBase64String($env:SIGNING_PFX_BASE64))
    $certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
        $pfxPath, $env:SIGNING_PFX_PASSWORD,
        [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
    $result = Set-AuthenticodeSignature -LiteralPath $File -Certificate $certificate -HashAlgorithm SHA256 -TimestampServer 'http://timestamp.digicert.com'
    if ($result.Status -ne 'Valid') { throw "Signing failed: $($result.Status)" }
} finally {
    if (Test-Path -LiteralPath $pfxPath) { Remove-Item -LiteralPath $pfxPath }
    if ($certificate) { $certificate.Dispose() }
}
