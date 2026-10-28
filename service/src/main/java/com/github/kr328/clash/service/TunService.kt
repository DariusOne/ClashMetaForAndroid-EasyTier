package com.github.kr328.clash.service

import android.annotation.TargetApi
import android.app.PendingIntent
import android.content.Intent
import android.net.ProxyInfo
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.LinkAddress
import android.net.IpPrefix
import android.net.RouteInfo
import android.net.VpnService
import android.os.Build
import com.github.kr328.clash.common.compat.pendingIntentFlags
import com.github.kr328.clash.common.constants.Components
import com.github.kr328.clash.common.log.Log
import com.github.kr328.clash.service.clash.clashRuntime
import com.github.kr328.clash.service.clash.module.*
import com.github.kr328.clash.service.model.AccessControlMode
import com.github.kr328.clash.service.store.ServiceStore
import com.github.kr328.clash.service.easytier.PacketHarness
import com.github.kr328.clash.service.easytier.VpnLinkCommit
import com.github.kr328.clash.core.easytier.NativePacketRouter
import com.github.kr328.clash.service.util.cancelAndJoinBlocking
import com.github.kr328.clash.service.util.parseCIDR
import com.github.kr328.clash.service.util.sendClashStarted
import com.github.kr328.clash.service.util.sendClashStopped
import kotlinx.coroutines.*
import kotlinx.coroutines.selects.select
import java.net.InetAddress

class TunService : VpnService(), CoroutineScope by CoroutineScope(Dispatchers.Default) {
    private val self: TunService
        get() = this

    private var reason: String? = null
    private var meshHarness: PacketHarness? = null

    private val runtime = clashRuntime {
        val store = ServiceStore(self)

        val close = install(CloseModule(self))
        val tun = install(TunModule(self))
        val config = install(ConfigurationModule(self))
        val network = install(NetworkObserveModule(self))

        if (store.dynamicNotification)
            install(DynamicNotificationModule(self))
        else
            install(StaticNotificationModule(self))

        install(AppListCacheModule(self))
        install(TimeZoneModule(self))
        install(SuspendModule(self))

        try {
            tun.open()

            while (isActive) {
                val quit = select<Boolean> {
                    close.onEvent {
                        true
                    }
                    config.onEvent {
                        reason = it.message

                        true
                    }
                    network.onEvent { n ->
                        if (Build.VERSION.SDK_INT in 22..28) @TargetApi(22) {
                            setUnderlyingNetworks(n?.let { arrayOf(it) })
                        }

                        false
                    }
                }

                if (quit) break
            }
        } catch (e: Exception) {
            Log.e("Create clash runtime: ${e.message}", e)

            reason = e.message
        } finally {
            withContext(NonCancellable) {
                try { meshHarness?.close() } finally { tun.close() }
                meshHarness = null

                stopSelf()
            }
        }
    }

    override fun onCreate() {
        super.onCreate()

        if (StatusProvider.serviceRunning)
            return stopSelf()

        StatusProvider.serviceRunning = true

        StaticNotificationModule.createNotificationChannel(this)
        StaticNotificationModule.notifyLoadingNotification(this)

        runtime.launch()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        sendClashStarted()

        return super.onStartCommand(intent, flags, startId)
    }

    override fun onDestroy() {
        TunModule.requestStop()

        StatusProvider.serviceRunning = false

        sendClashStopped(reason)

        cancelAndJoinBlocking()

        Log.i("TunService destroyed: ${reason ?: "successfully"}")

        super.onDestroy()
    }

    override fun onTrimMemory(level: Int) {
        super.onTrimMemory(level)

        runtime.requestGc()
    }

    private suspend fun TunModule.open() {
        val store = ServiceStore(self)
        val harness = PacketHarness.configured(self, self)
        meshHarness = harness
        if (harness != null) {
            check(!store.systemProxy) { "ET_PACKET_HARNESS_NO_HTTP_PROXY" }
            harness.open(this, allowRouteGrowth = !store.bypassPrivateNetwork) { addresses, routes ->
                buildDevice(store, addresses, routes, true)
            }
        } else {
            attach(buildDevice(store, emptyList(), emptySet(), false))
        }
    }

    private suspend fun TunModule.buildDevice(store: ServiceStore, meshAddresses: List<PacketHarness.Address>, meshRoutes: Set<String>, nativeMesh: Boolean): TunModule.TunDevice {
        return with(Builder()) {
            val requiredRoutes = linkedSetOf<String>()
            fun route(address: String, bits: Int) {
                addRoute(address, bits)
                requiredRoutes.add(IpPrefix(InetAddress.getByName(address), bits).toString())
            }
            // Interface address
            // The mesh address is first so native packets use the phone's mesh
            // identity; source selection remains a required real-device test.
            meshAddresses.forEach { addAddress(it.ip, it.bits) }
            addAddress(TUN_GATEWAY, TUN_SUBNET_PREFIX)
            if (store.allowIpv6) {
                addAddress(TUN_GATEWAY6, TUN_SUBNET_PREFIX6)
            }

            // Route
            if (store.bypassPrivateNetwork) {
                resources.getStringArray(R.array.bypass_private_route).map(::parseCIDR).forEach {
                    route(it.ip, it.prefix)
                }
                if (store.allowIpv6) {
                    resources.getStringArray(R.array.bypass_private_route6).map(::parseCIDR).forEach {
                        route(it.ip, it.prefix)
                    }
                }

                // Route of virtual DNS
                route(TUN_DNS, 32)
                if (store.allowIpv6) {
                    route(TUN_DNS6, 128)
                }
            } else {
                route(NET_ANY, 0)
                if (store.allowIpv6) {
                    route(NET_ANY6, 0)
                }
            }

            if (nativeMesh) {
                meshRoutes.map(::parseCIDR).forEach { route(it.ip, it.prefix) }
                route("255.255.255.255", 32)
                route("224.0.0.251", 32)
                route("239.255.255.250", 32)
                if (meshAddresses.any { it.ip.contains(":") }) {
                    route("ff02::fb", 128)
                    route("ff02::c", 128)
                }
            }

            // Access Control
            when (store.accessControlMode) {
                AccessControlMode.AcceptAll -> if (nativeMesh) addDisallowedApplication(packageName) else Unit
                AccessControlMode.AcceptSelected -> {
                    val packages = if (nativeMesh) store.accessControlPackages - packageName else store.accessControlPackages + packageName
                    var added = 0
                    packages.forEach {
                        runCatching { addAllowedApplication(it) }.onSuccess { added++ }
                    }
                    if (nativeMesh) check(added > 0) { "ET_EMPTY_ALLOWED_APPLICATIONS" }
                }
                AccessControlMode.DenySelected -> {
                    val packages = if (nativeMesh) store.accessControlPackages + packageName else store.accessControlPackages - packageName
                    packages.forEach {
                        if (nativeMesh && it == packageName) addDisallowedApplication(it)
                        else
                        runCatching { addDisallowedApplication(it) }
                    }
                }
            }

            // Blocking
            setBlocking(false)

            // Mtu
            setMtu(if (nativeMesh) 1380 else TUN_MTU)

            // Session Name
            setSession(if (nativeMesh) "CMFA + EasyTier packet prototype" else "Clash")

            // Virtual Dns Server
            addDnsServer(TUN_DNS)
            if (store.allowIpv6) {
                addDnsServer(TUN_DNS6)
            }

            // Open MainActivity
            setConfigureIntent(
                PendingIntent.getActivity(
                    self,
                    R.id.nf_vpn_status,
                    Intent().setComponent(Components.MAIN_ACTIVITY),
                    pendingIntentFlags(PendingIntent.FLAG_UPDATE_CURRENT)
                )
            )

            // Metered
            if (Build.VERSION.SDK_INT >= 29) {
                setMetered(false)
            }

            // System Proxy
            if (Build.VERSION.SDK_INT >= 29 && store.systemProxy) {
                listenHttp()?.let {
                    setHttpProxy(
                        ProxyInfo.buildDirectProxy(
                            it.address.hostAddress,
                            it.port,
                            HTTP_PROXY_BLACK_LIST + if (store.bypassPrivateNetwork) HTTP_PROXY_LOCAL_LIST else emptyList()
                        )
                    )
                }
            }

            if (store.allowBypass) {
                allowBypass()
            }

            val descriptor = establish()
                ?: throw NullPointerException("Establish VPN rejected by system")
            descriptor.use {
                if (nativeMesh) {
                    val name = NativePacketRouter.interfaceName(it.fd)
                        ?: error("ET_INTERFACE_NAME_UNAVAILABLE")
                    val addresses = (meshAddresses.map { address -> address.cidr } +
                        "$TUN_GATEWAY/$TUN_SUBNET_PREFIX" +
                        if (store.allowIpv6) listOf("$TUN_GATEWAY6/$TUN_SUBNET_PREFIX6") else emptyList())
                        .map { address -> parseCIDR(address).let { cidr -> LinkAddress(InetAddress.getByName(cidr.ip), cidr.prefix).toString() } }.toSet()
                    val expected = VpnLinkCommit(name, addresses, requiredRoutes)
                    val connectivity = getSystemService(ConnectivityManager::class.java)
                        ?: error("ET_CONNECTIVITY_UNAVAILABLE")
                    // establish() returns before ConnectivityService processes
                    // the new LinkProperties/routes. Keep the old descriptor and
                    // dispatcher paused until the exact new interface is visible.
                    // This acknowledges readiness, not an OS-wide lockdown during
                    // the platform's handover window.
                    withTimeout(5_000) {
                        while (true) {
                            val committed = connectivity.allNetworks.any { network ->
                                val capabilities = connectivity.getNetworkCapabilities(network)
                                val link = connectivity.getLinkProperties(network)
                                link != null && capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true &&
                                    expected.matches(link.interfaceName,
                                        link.linkAddresses.map { address -> address.toString() }.toSet(),
                                        link.routes.filter { route -> route.type == RouteInfo.RTN_UNICAST }
                                            .map { route -> route.destination.toString() }.toSet())
                            }
                            if (committed) break
                            delay(10)
                        }
                    }
                }
                TunModule.TunDevice(
                    fd = it.detachFd(),
                    stack = store.tunStackMode,
                    gateway = "$TUN_GATEWAY/$TUN_SUBNET_PREFIX" + if (store.allowIpv6) ",$TUN_GATEWAY6/$TUN_SUBNET_PREFIX6" else "",
                    portal = TUN_PORTAL + if (store.allowIpv6) ",$TUN_PORTAL6" else "",
                    dns = if (store.dnsHijacking) NET_ANY else (TUN_DNS + if (store.allowIpv6) ",$TUN_DNS6" else ""),
                )
            }
        }

    }

    companion object {
        private const val TUN_MTU = 9000
        private const val TUN_SUBNET_PREFIX = 30
        private const val TUN_GATEWAY = "172.19.0.1"
        private const val TUN_SUBNET_PREFIX6 = 126
        private const val TUN_GATEWAY6 = "fdfe:dcba:9876::1"
        private const val TUN_PORTAL = "172.19.0.2"
        private const val TUN_PORTAL6 = "fdfe:dcba:9876::2"
        private const val TUN_DNS = TUN_PORTAL
        private const val TUN_DNS6 = TUN_PORTAL6
        private const val NET_ANY = "0.0.0.0"
        private const val NET_ANY6 = "::"

        private val HTTP_PROXY_LOCAL_LIST: List<String> = listOf(
            "localhost",
            "*.local",
            "127.*",
            "10.*",
            "172.16.*",
            "172.17.*",
            "172.18.*",
            "172.19.*",
            "172.2*",
            "172.30.*",
            "172.31.*",
            "192.168.*"
        )
        private val HTTP_PROXY_BLACK_LIST: List<String> = listOf(
            "*zhihu.com",
            "*zhimg.com",
            "*jd.com",
            "100ime-iat-api.xfyun.cn",
            "*360buyimg.com",
        )
    }
}
