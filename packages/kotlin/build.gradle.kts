plugins {
    kotlin("jvm") version "2.4.21"
    kotlin("plugin.serialization") version "2.4.21"
    application
}

group = "net.biz59.zoflib.cloud"
version = "0.1.0"

dependencies {
    implementation(awssdk.services.s3)
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.0")
    testImplementation(kotlin("test"))
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.1")
}

kotlin { jvmToolchain(11) }

application {
    mainClass = "net.biz59.zoflib.cloud.conformance.DriverKt"
    applicationDefaultJvmArgs = listOf("-Dfile.encoding=UTF-8")
}

tasks.test { useJUnitPlatform() }

tasks.register<JavaExec>("conformanceDriver") {
    group = "verification"
    classpath = sourceSets.main.get().runtimeClasspath
    mainClass = application.mainClass
    standardInput = System.`in`
}
