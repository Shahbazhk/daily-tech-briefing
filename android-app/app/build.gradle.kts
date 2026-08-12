plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    // Re-add "com.google.gms.google-services" here (and its classpath in the root
    // build.gradle.kts) once Firebase is set up and app/google-services.json exists —
    // see EpisodeRepository's TODO. Left out for now so the app builds and installs
    // without needing a Firebase project first (BRD Section 14.5 fallback path).
}

android {
    namespace = "com.shahbaz.dailytechupdates"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.shahbaz.dailytechupdates"
        // minSdk 26 (Android 8.0+) lets us use adaptive icons without shipping legacy PNGs,
        // and covers the vast majority of devices for a single-user personal app.
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        viewBinding = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")

    // Podcast playback - Google's open-source Media3/ExoPlayer.
    implementation("androidx.media3:media3-exoplayer:1.4.1")
    implementation("androidx.media3:media3-ui:1.4.1")

    implementation("androidx.recyclerview:recyclerview:1.3.2")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    testImplementation("junit:junit:4.13.2")
    // android.jar's org.json classes are stubs in local unit tests (throw "not mocked");
    // this pulls in the real reference implementation for the JVM test classpath.
    testImplementation("org.json:json:20240303")
}
