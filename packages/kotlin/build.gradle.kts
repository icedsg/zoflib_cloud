plugins {
    kotlin("jvm") version "2.4.21"
    kotlin("plugin.serialization") version "2.4.21"
    `java-library`
    `maven-publish`
    signing
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

java {
    withSourcesJar()
    withJavadocJar()
}

val driver by sourceSets.creating {
    kotlin.srcDir("src/driver/kotlin")
    compileClasspath += sourceSets.main.get().output
    runtimeClasspath += output + compileClasspath
}

configurations[driver.implementationConfigurationName].extendsFrom(configurations.implementation.get())
configurations[driver.runtimeOnlyConfigurationName].extendsFrom(configurations.runtimeOnly.get())
sourceSets.test {
    compileClasspath += driver.output
    runtimeClasspath += driver.output
}

application {
    mainClass = "net.biz59.zoflib.cloud.conformance.DriverKt"
    applicationDefaultJvmArgs = listOf("-Dfile.encoding=UTF-8")
}

tasks.named<JavaExec>("run") { classpath = driver.runtimeClasspath }
val driverJar by tasks.registering(Jar::class) {
    archiveClassifier = "driver"
    from(driver.output)
}
tasks.named<CreateStartScripts>("startScripts") {
    classpath = files(driverJar, tasks.jar) + configurations.runtimeClasspath.get()
}
distributions {
    main {
        contents {
            from(driverJar) { into("lib") }
        }
    }
}

tasks.test { useJUnitPlatform() }

tasks.register<JavaExec>("conformanceDriver") {
    group = "verification"
    classpath = driver.runtimeClasspath
    mainClass = application.mainClass
    standardInput = System.`in`
}

publishing {
    publications {
        create<MavenPublication>("maven") {
            from(components["java"])
            artifactId = "zoflib-cloud"
            pom {
                name = "zoflib-cloud"
                description = "Provider-neutral cloud storage contract with a generic S3 adapter."
                url = "https://github.com/icedsg/zoflib_cloud"
                licenses {
                    license {
                        name = "MIT License"
                        url = "https://opensource.org/license/mit"
                        distribution = "repo"
                    }
                }
                developers {
                    developer {
                        id = "biz59"
                        name = "Biz59 LLC"
                    }
                }
                scm {
                    connection = "scm:git:https://github.com/icedsg/zoflib_cloud.git"
                    developerConnection = "scm:git:ssh://git@github.com/icedsg/zoflib_cloud.git"
                    url = "https://github.com/icedsg/zoflib_cloud"
                }
            }
        }
    }
}

signing {
    val signingKey = providers.gradleProperty("signingInMemoryKey").orNull
    val signingPassword = providers.gradleProperty("signingInMemoryKeyPassword").orNull
    isRequired = signingKey != null
    if (signingKey != null) useInMemoryPgpKeys(signingKey, signingPassword)
    sign(publishing.publications["maven"])
}
