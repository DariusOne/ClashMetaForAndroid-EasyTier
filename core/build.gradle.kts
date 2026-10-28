import android.databinding.tool.ext.capitalizeUS
import com.github.kr328.golang.GolangBuildTask
import com.github.kr328.golang.GolangPlugin
import java.security.MessageDigest

plugins {
    kotlin("android")
    id("com.android.library")
    id("kotlinx-serialization")
    id("golang-android")
}

val golangSource = file("src/main/golang/native")

// Keep the upstream submodule pinned. A hash-checked local compatibility fix
// consumes buffers on REJECT writes; debug leak checks remain enabled.
val prepareMihomo = tasks.register<Exec>("prepareMihomo") {
    workingDir(rootProject.projectDir)
    val python = providers.gradleProperty("pythonExecutable").orNull
        ?: if (System.getProperty("os.name").startsWith("Windows")) "python" else "python3"
    commandLine(python, rootProject.file("scripts/prepare-mihomo.py"))
}

golang {
    sourceSets {
        create("alpha") {
            tags.set(listOf("foss","with_gvisor","cmfa"))
            srcDir.set(file("src/foss/golang"))
        }
        create("meta") {
            tags.set(listOf("foss","with_gvisor","cmfa"))
            srcDir.set(file("src/foss/golang"))
        }
        all {
            fileName.set("libclash.so")
            packageName.set("cfa/native")
        }
    }
}

android {
    if (providers.gradleProperty("nativeMeshHarness").orNull == "true") {
        sourceSets.getByName("main").jniLibs.srcDir(layout.buildDirectory.dir("native-jni"))
    }
    productFlavors {
        all {
            externalNativeBuild {
                cmake {
                    arguments("-DGO_SOURCE:STRING=${golangSource}")
                    arguments("-DGO_OUTPUT:STRING=${GolangPlugin.outputDirOf(project, null, null)}")
                    arguments("-DFLAVOR_NAME:STRING=$name")
                }
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
        }
    }
}

dependencies {
    implementation(project(":common"))

    implementation(libs.androidx.core)
    implementation(libs.kotlin.coroutine)
    implementation(libs.kotlin.serialization.json)
}

afterEvaluate {
    tasks.withType(GolangBuildTask::class.java).forEach {
        it.dependsOn(prepareMihomo)
        it.inputs.dir(golangSource)
        it.inputs.dir(rootProject.file("native/packet-router"))
    }
    if (providers.gradleProperty("nativeMeshHarness").orNull == "true") {
        val verify = tasks.register("verifyNativeMeshLibraries") {
            doLast {
                for (abi in listOf("arm64-v8a", "x86_64")) {
                    val dir = layout.buildDirectory.dir("native-jni/$abi").get().asFile
                    val library = dir.resolve("libcmfa_easytier.so")
                    val stamp = dir.resolve("build-info.json")
                    check(library.isFile && stamp.isFile) { "Build both pinned native mesh ABIs before the prototype APK" }
                    val hash = MessageDigest.getInstance("SHA-256").digest(library.readBytes()).joinToString("") { "%02x".format(it) }
                    check(stamp.readText().contains(hash)) { "Native mesh artifact checksum mismatch" }
                }
            }
        }
        tasks.named("preBuild").configure { dependsOn(verify) }
    }
}

val abis = listOf("arm64-v8a" to "Arm64V8a", "armeabi-v7a" to "ArmeabiV7a", "x86" to "X86", "x86_64" to "X8664")

androidComponents.onVariants { variant ->
    val cmakeName = if (variant.buildType == "debug") "Debug" else "RelWithDebInfo"

    abis.forEach { (abi, goAbi) ->
        tasks.configureEach {
            if (name.startsWith("buildCMake$cmakeName[$abi]")) {
                dependsOn("externalGolangBuild${variant.name.capitalizeUS()}$goAbi")
                println("Set up dependency: $name -> externalGolangBuild${variant.name.capitalizeUS()}$goAbi")
            }
        }
    }
}

