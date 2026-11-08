package com.biz59.zoflib.cloud

import java.io.InputStream
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
data class ProviderPreset(
    val id: String,
    val name: String,
    val protocol: String,
    val classification: String,
    @SerialName("endpoint_template") val endpointTemplate: String? = null,
    val region: String? = null,
    val addressing: String? = null,
    val caveats: String = "",
)

@Serializable private data class ProviderDocument(val providers: List<ProviderPreset>)

object ProviderPresets {
    private val json = Json { ignoreUnknownKeys = true }

    fun load(input: InputStream): Map<String, ProviderPreset> = input.bufferedReader(Charsets.UTF_8).use { reader ->
        json.decodeFromString<ProviderDocument>(reader.readText()).providers.associateBy { it.id }
    }
}
