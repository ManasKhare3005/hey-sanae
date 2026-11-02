plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("app.cash.paparazzi")   // renders the watch screen to PNG on the laptop (no watch needed)
}

// Galaxy Watch app: tap to talk, her face, approvals, a Today tile and a complication.
// It has no network code of its own: everything goes through the phone app (WatchRelay).
android {
    namespace = "com.manaskhare.sanae.watch"
    compileSdk = 35

    defaultConfig {
        // Must be the phone app's id (and signed with the same key) for the Wear OS Data Layer
        applicationId = "com.manaskhare.max"
        minSdk = 30
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.wear.compose:compose-material:1.4.0")
    implementation("androidx.wear.compose:compose-foundation:1.4.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.fragment:fragment-ktx:1.8.5")   // play-services pulls Fragment 1.0, which breaks activity results
    implementation("androidx.profileinstaller:profileinstaller:1.4.1")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.9.0")
    implementation("com.google.android.gms:play-services-wearable:18.2.0")
    implementation("androidx.health:health-services-client:1.0.0")   // heart rate on request (health sharing on)
    // Today tile + "talk" complication
    implementation("androidx.wear.tiles:tiles:1.4.1")
    implementation("androidx.wear.protolayout:protolayout:1.2.1")
    implementation("androidx.wear.protolayout:protolayout-material:1.2.1")
    implementation("androidx.wear.watchface:watchface-complications-data-source-ktx:1.2.1")
    implementation("com.google.guava:guava:33.3.1-android")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
