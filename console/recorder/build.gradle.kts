plugins {
    id("com.android.application") version "9.1.0"
}

val vitureJniLibs = System.getenv("VITURE_SDK_LIBS")
    ?: "${System.getProperty("user.home")}/workspace/uxspace/Android/glasses/src/main/jniLibs"
val vitureInclude = System.getenv("VITURE_SDK_INCLUDE")
    ?: "${System.getProperty("user.home")}/workspace/uxspace/Android/SDK/linux-x86_64/include"
val glassesSo = file("$vitureJniLibs/arm64-v8a/libglasses.so")
if (!glassesSo.isFile) {
    throw GradleException(
        "VITURE SDK libglasses.so missing at $glassesSo. " +
            "Set VITURE_SDK_LIBS to the arm64 jniLibs tree used by UxSpace. Do not commit the .so files."
    )
}

android {
    namespace = "sh.colak.xrconsole.recorder"
    compileSdk = 36
    ndkVersion = "30.0.14904198"

    defaultConfig {
        applicationId = "sh.colak.xrconsole.recorder"
        minSdk = 30
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        ndk { abiFilters += "arm64-v8a" }
        externalNativeBuild {
            cmake {
                cppFlags += "-std=c++17"
                arguments += listOf(
                    "-DVITURE_INCLUDE_DIR=$vitureInclude",
                    "-DVITURE_JNILIBS_DIR=$vitureJniLibs/arm64-v8a",
                )
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "4.1.2"
        }
    }

    sourceSets {
        getByName("main") {
            jniLibs.srcDir(vitureJniLibs)
        }
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }

    lint { abortOnError = false }
}
