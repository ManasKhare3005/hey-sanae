plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("app.cash.paparazzi")   // renders screens to PNG on the laptop (no device)
}

android {
    namespace = "com.manaskhare.sanae"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.manaskhare.max"
        minSdk = 29
        targetSdk = 35
        versionCode = 1
        versionName = "0.4.0"
        // Settings -> App update compares this with the APK the laptop last built
        buildConfigField("long", "BUILD_TIME", "${System.currentTimeMillis()}L")
    }

    buildTypes {
        release {
            isMinifyEnabled = true       // R8: optimised Compose (see proguard-rules.pro)
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
    testOptions { unitTests.isIncludeAndroidResources = true }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.fragment:fragment-ktx:1.8.5")   // zxing / play-services pull Fragment 1.0, which breaks activity results
    implementation("androidx.profileinstaller:profileinstaller:1.4.1")   // installs Compose's baseline profiles: precompiled, smooth from the first launch
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")   // QR pairing
    implementation("com.google.android.gms:play-services-wearable:18.2.0")   // the Galaxy Watch app talks through here
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.9.0")
    implementation("androidx.glance:glance-appwidget:1.1.1")
    implementation("androidx.health.connect:connect-client:1.1.0-alpha11")   // watch sleep / steps / heart rate (off until turned on)      // the Today & todo home-screen widget
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.14.1")
    testImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    testImplementation("org.json:json:20240303")    // Android's org.json is only a stub in JVM tests
}
