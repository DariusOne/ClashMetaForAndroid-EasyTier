package com.github.kr328.clash.service.easytier

/** Credential-free handover acknowledgement, after platform route processing.
 * The old interface can have identical addresses; its identity is insufficient.
 */
internal data class VpnLinkCommit(
    val interfaceName: String,
    val addresses: Set<String>,
    val routes: Set<String>,
) {
    init { require(interfaceName.isNotBlank() && addresses.isNotEmpty() && routes.isNotEmpty()) }

    fun matches(name: String?, installedAddresses: Set<String>, installedRoutes: Set<String>): Boolean =
        name == interfaceName && installedAddresses.containsAll(addresses) && installedRoutes.containsAll(routes)
}
