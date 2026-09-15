plugins {
    id("java")
    id("org.jetbrains.intellij.platform") version "2.2.1"
}

group = "dev.erid"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        intellijIdeaCommunity("2024.3")
    }
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
}

intellijPlatform {
    pluginConfiguration {
        name = "AI Context Hub"
        ideaVersion {
            sinceBuild = "243"
        }
    }
}

tasks {
    wrapper {
        gradleVersion = "8.12"
    }
}
