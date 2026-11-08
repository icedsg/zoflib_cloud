package com.biz59.zoflib.cloud

import java.io.ByteArrayInputStream
import kotlin.test.*

class ModelsTest {
    @Test fun `plain HTTP needs explicit development opt in`() {
        assertFailsWith<IllegalArgumentException> {
            ConnectionConfig("minio", "http://127.0.0.1:9000", "us-east-1", credentialRef = "test")
        }
        ConnectionConfig("minio", "http://127.0.0.1:9000", "us-east-1", credentialRef = "test", allowInsecureHttp = true)
    }

    @Test fun `provider loader accepts the shared catalog shape`() {
        val source = """{"contract_version":"0.1.0","providers":[{"id":"minio","name":"MinIO","protocol":"s3","classification":"compatible_by_protocol","self_hosted":true,"endpoint_template":null,"region":"us-east-1","addressing":"both","caveats":"none"}]}"""
        val preset = ProviderPresets.load(ByteArrayInputStream(source.encodeToByteArray())).getValue("minio")
        assertEquals("s3", preset.protocol)
        assertNull(preset.endpointTemplate)
    }

    @Test fun `capabilities do not promise unfinished multipart`() {
        assertTrue("upload" in S3_CAPABILITIES)
        assertFalse("multipart_upload" in S3_CAPABILITIES)
    }

    @Test fun `UTF8 comparator follows byte order`() {
        val values = listOf("\uD800\uDC00", "\uE000")
        assertEquals(listOf("\uE000", "\uD800\uDC00"), values.sortedWith(utf8Comparator))
    }
}
