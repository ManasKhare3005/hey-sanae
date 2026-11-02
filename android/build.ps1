# Build the Sanae phone app and the Galaxy Watch app (release APKs: debug builds run Compose without optimisations, typing lagged) and install them on whatever is
# connected over adb: a USB phone, and/or a watch with Wi-Fi debugging (see android/WATCH.md).
# Uses the JDK + Android SDK in C:\max-android (no Android Studio needed).
#   .\android\build.ps1            build + install on connected devices
#   .\android\build.ps1 -NoInstall build only
param([switch]$NoInstall)
$ErrorActionPreference = "Stop"
$tools = "C:\max-android"
$env:JAVA_HOME = "$tools\jdk17"
$env:ANDROID_HOME = "$tools\sdk"
$env:Path = "$tools\jdk17\bin;$tools\sdk\platform-tools;$env:Path"

Push-Location $PSScriptRoot
try {
    if (-not (Test-Path local.properties)) { "sdk.dir=C\:/max-android/sdk" | Out-File -Encoding ascii local.properties }
    & .\gradlew.bat assembleRelease --console=plain
    if ($LASTEXITCODE -ne 0) { throw "Gradle build failed" }
    $apk = Resolve-Path "app\build\outputs\apk\release\app-release.apk"
    $wear = Resolve-Path "wear\build\outputs\apk\release\wear-release.apk"
    Write-Host "APK: $apk"
    Write-Host "Watch APK: $wear"
    # The phone app's Settings -> Update installs this copy (served by Sanae over Tailscale)
    $published = Join-Path $PSScriptRoot "..\data\app"
    New-Item -ItemType Directory -Force $published | Out-Null
    Copy-Item $apk (Join-Path $published "sanae.apk") -Force
    Copy-Item $wear (Join-Path $published "sanae-wear.apk") -Force
    if ($NoInstall) { return }
    # adb prints "daemon not running; starting now" on stderr, which Stop would treat as a failure
    $ErrorActionPreference = "Continue"
    & adb start-server 2>$null | Out-Null
    $devices = (& adb devices) | Select-Object -Skip 1 | Where-Object { $_ -match "\tdevice$" } |
        ForEach-Object { ($_ -split "\t")[0] }
    if (-not $devices) {
        Write-Host "No phone or watch connected (enable USB / Wi-Fi debugging), or copy the APK to the phone and open it."
        return
    }
    foreach ($d in $devices) {
        # the watch and phone apps share one app id: each device gets its own build
        $isWatch = (& adb -s $d shell getprop ro.build.characteristics) -match "watch"
        if ($isWatch) { Write-Host "Watch: $d"; & adb -s $d install -r $wear }
        else { Write-Host "Phone: $d"; & adb -s $d install -r $apk }
    }
} finally {
    Pop-Location
}
