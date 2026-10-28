package com.github.kr328.clash.service.easytier

import org.junit.Assert.*
import org.junit.Test

class VpnLinkCommitTest {
    private val addresses = setOf("10.126.0.2/24", "172.19.0.1/30")
    private val routes = setOf("0.0.0.0/0", "10.126.0.0/24", "224.0.0.251/32")
    private val commit = VpnLinkCommit("tun1", addresses, routes)

    @Test fun identicalOldLinkCannotAcknowledgeNewInterface() {
        assertFalse(commit.matches("tun0", addresses, routes))
        assertFalse(commit.matches(null, addresses, routes))
        assertTrue(commit.matches("tun1", addresses, routes))
    }

    @Test fun addressesAloneCannotAcknowledgePendingRoutes() {
        assertFalse(commit.matches("tun1", addresses, emptySet()))
        assertFalse(commit.matches("tun1", addresses, routes - "10.126.0.0/24"))
        assertFalse(commit.matches("tun1", addresses - "10.126.0.2/24", routes))
        assertTrue(commit.matches("tun1", addresses, routes + "172.19.0.0/30"))
    }

    @Test fun ipv6AndBypassRoutesMustAlsoBeCommitted() {
        val v6 = VpnLinkCommit("tun1", setOf("fd00::2/64"), setOf("fd00::/64", "ff02::fb/128"))
        assertFalse(v6.matches("tun1", setOf("fd00::2/64"), setOf("fd00::/64")))
        assertTrue(v6.matches("tun1", setOf("fd00::2/64"), setOf("fd00::/64", "ff02::fb/128")))
    }
}
