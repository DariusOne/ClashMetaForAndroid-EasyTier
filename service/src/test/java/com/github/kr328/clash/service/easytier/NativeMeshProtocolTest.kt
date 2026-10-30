package com.github.kr328.clash.service.easytier

import org.junit.Assert.assertEquals
import org.junit.Test

class NativeMeshProtocolTest {
    @Test fun importedErrorsCannotEscapeAsDiagnostics() {
        for (input in listOf("ET_USER_SECRET", "ET_START_FAILED password=fixture", "https://fixture.invalid/?token=private", "secret-fixture")) {
            assertEquals("ET_ENGINE_COMMAND_FAILED", NativeMeshProtocol.safeError(IllegalStateException(input)))
        }
        assertEquals("ET_ENGINE_COMMAND_FAILED", NativeMeshProtocol.safeError(IllegalStateException()))
    }

    @Test fun knownNativeAndLinkErrorsRemainActionable() {
        assertEquals("ET_PACKET_DEVICE_FAILED", NativeMeshProtocol.safeError(IllegalStateException("ET_PACKET_DEVICE_FAILED")))
        assertEquals("ET_CONFIG_SYNTAX", NativeMeshProtocol.safeError(IllegalStateException("ET_CONFIG_SYNTAX")))
        assertEquals("ET_NATIVE_LINK_FAILED", NativeMeshProtocol.safeError(UnsatisfiedLinkError("private-path-or-library-message")))
    }
}
