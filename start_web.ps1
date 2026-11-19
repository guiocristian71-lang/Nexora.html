$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$env:GESTOR_PC_DB = Join-Path $PSScriptRoot "web-data\mantenimiento.db"

$secretDirectory = Join-Path $env:LOCALAPPDATA "GestorPCWeb"
New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
$secretPath = Join-Path $secretDirectory "secret_key"
if (-not (Test-Path $secretPath)) {
    $generatedSecret = & python -c "import secrets; print(secrets.token_hex(32))"
    if ($LASTEXITCODE -ne 0 -or -not $generatedSecret) {
        throw "No se pudo generar la clave secreta de la aplicación."
    }
    [System.IO.File]::WriteAllText(
        $secretPath,
        $generatedSecret.Trim(),
        [System.Text.Encoding]::ASCII
    )
}
$env:GESTOR_PC_SECRET_KEY = (Get-Content -Raw $secretPath).Trim()

$userCountScript = "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); t=c.execute('SELECT COUNT(*) FROM sqlite_master WHERE name = ?', ('usuarios',)).fetchone()[0]; print(c.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0] if t else 0)"
$userCount = & python -c $userCountScript $env:GESTOR_PC_DB
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo comprobar la base de datos de la web."
}
if ([int]$userCount -eq 0) {
    $env:GESTOR_PC_USERNAME = Read-Host "Nombre para la cuenta administradora inicial"
    $securePassword = Read-Host "Contraseña de administrador (mínimo 12 caracteres)" -AsSecureString
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        $env:GESTOR_PC_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    if ($env:GESTOR_PC_PASSWORD.Length -lt 12) {
        throw "La contraseña debe tener al menos 12 caracteres."
    }
}

$restartDelaySeconds = 3

while ($true) {
    try {
        python -m waitress --listen=127.0.0.1:5000 web:app
        $exitCode = $LASTEXITCODE
    }
    catch {
        $exitCode = 1
        Write-Host "Error al ejecutar el servidor: $($_.Exception.Message)"
    }

    Write-Host "El servidor se detuvo (codigo $exitCode). Reiniciando en $restartDelaySeconds segundos..."
    Start-Sleep -Seconds $restartDelaySeconds
}
