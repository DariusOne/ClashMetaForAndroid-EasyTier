package com.github.kr328.clash.service.easytier

import org.junit.Assert.*
import org.junit.Test

class LegacyVpnHandoverTest {
    @Test fun repeatedVerifiedPackagePreservesAllowedOrDeniedSet() {
        for (packages in listOf(listOf("vpn.owner"), listOf("app.one", "app.two"))) {
            val handover = LegacyVpnHandover()
            var previous: List<String>? = null
            repeat(4) {
                val current = packages + listOfNotNull(handover.repeatEntry(30, true, packages))
                assertEquals(packages.toSet(), current.toSet())
                if (previous != null) assertNotEquals(previous, current)
                previous = current
                handover.committed(30, true)
            }
        }
    }

    @Test fun normalCmfaAndOtherVersionsKeepOriginalApplicationList() {
        val handover = LegacyVpnHandover()
        handover.committed(30, true)
        for (api in listOf(21, 29, 31, 37)) assertNull(handover.repeatEntry(api, true, listOf("owner")))
        assertNull(handover.repeatEntry(30, false, listOf("owner")))
        assertNull(handover.repeatEntry(30, true, emptyList()))
    }
}
