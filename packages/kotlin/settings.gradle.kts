rootProject.name = "zoflib-cloud-kotlin"

dependencyResolutionManagement {
    repositories { mavenCentral() }
    versionCatalogs {
        create("awssdk") { from("aws.sdk.kotlin:version-catalog:1.9.32") }
    }
}
