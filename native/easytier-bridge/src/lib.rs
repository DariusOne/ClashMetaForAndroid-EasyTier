//! Native EasyTier adapter. No VpnService, interface creation or config logging.
//! Android supplies an owned packet endpoint after establishing transport
//! isolation. This crate is not yet enabled in the production service.

use easytier::{
    common::config::{ConfigFileControl, ConfigLoader, Flags, TomlConfigLoader, gen_default_flags},
    common::global_ctx::GlobalCtxEvent,
    instance_manager::NetworkInstanceManager,
};
use jni::{
    JNIEnv,
    objects::{JObject, JString},
    sys::{jboolean, jint, jlong, jstring},
};
use serde_json::json;
#[cfg(unix)]
use std::os::fd::{FromRawFd, OwnedFd};
use std::{
    ptr,
    sync::{LazyLock, Mutex},
};

const MAX_CONFIG_BYTES: usize = 1024 * 1024;

struct Session {
    generation: i64,
    id: uuid::Uuid,
    // Drop the engine (which joins its workers) BEFORE the borrowed packet fd.
    manager: NetworkInstanceManager,
    configured_ipv6: Option<String>,
    packet_ready: bool,
    #[cfg(unix)]
    packet: Option<OwnedFd>,
}

impl Drop for Session {
    fn drop(&mut self) {
        let _ = self.manager.retain_network_instance(Vec::new());
    }
}

static SESSION: LazyLock<Mutex<Option<Session>>> = LazyLock::new(|| Mutex::new(None));

// Upstream queues the descriptor asynchronously. Only its matching successful
// device event acknowledges initialization; queuing a descriptor is insufficient.
fn packet_event(event: GlobalCtxEvent, expected: &str) -> Result<bool, &'static str> {
    match event {
        GlobalCtxEvent::TunDeviceReady(name) => Ok(name == expected),
        GlobalCtxEvent::TunDeviceError(_) => Err("ET_PACKET_DEVICE_FAILED"),
        _ => Ok(false),
    }
}

// Failures use fixed codes; upstream parser errors may contain passwords/URIs.
fn config(text: &str, id: uuid::Uuid) -> Result<TomlConfigLoader, &'static str> {
    if text.len() > MAX_CONFIG_BYTES || text.is_empty() {
        return Err("ET_CONFIG_SIZE");
    }
    let doc: toml::Value = toml::from_str(text).map_err(|_| "ET_CONFIG_SYNTAX")?;
    // No file imports, management portals or host routing from a mobile profile.
    for key in [
        "credential_file",
        "rpc_portal",
        "socks5_portal",
        "socks5_proxy",
        "vpn_portal",
        "vpn_portal_config",
        "port_forward",
        "port_forwards",
        "netns",
        "file_logger",
        "source",
        "proxy_network",
    ] {
        if doc.get(key).is_some() {
            return Err("ET_UNSUPPORTED_HOST_OPTION");
        }
    }
    // Upstream merges flags and unwraps deserialization. Validate the exact
    // merged representation first: malformed imports must not abort the JVM.
    let mut flags = serde_json::to_value(gen_default_flags()).map_err(|_| "ET_CONFIG_INVALID")?;
    if let Some(input) = doc.get("flags") {
        let input = input.as_table().ok_or("ET_FLAGS_INVALID")?;
        let defaults = flags.as_object_mut().ok_or("ET_CONFIG_INVALID")?;
        for (key, value) in input {
            if !defaults.contains_key(key) {
                return Err("ET_FLAG_UNKNOWN");
            }
            defaults.insert(
                key.clone(),
                serde_json::to_value(value).map_err(|_| "ET_FLAGS_INVALID")?,
            );
        }
    }
    let flags: Flags = serde_json::from_value(flags).map_err(|_| "ET_FLAGS_INVALID")?;
    if flags.enable_exit_node || flags.proxy_forward_by_system {
        return Err("ET_UNSUPPORTED_HOST_OPTION");
    }
    if !(1280..=1380).contains(&flags.mtu) {
        return Err("ET_MTU_INVALID");
    }
    let cfg = TomlConfigLoader::new_from_str(text).map_err(|_| "ET_CONFIG_INVALID")?;
    if !cfg.get_exit_nodes().is_empty()
        || cfg
            .get_routes()
            .unwrap_or_default()
            .iter()
            .any(|r| r.network_length() == 0)
    {
        return Err("ET_DEFAULT_ROUTE_FORBIDDEN");
    }
    if cfg.get_flags().no_tun || cfg.get_flags().use_smoltcp {
        return Err("ET_PACKET_DEVICE_REQUIRED");
    }
    if doc
        .get("network_identity")
        .and_then(|v| v.get("network_name"))
        .and_then(|v| v.as_str())
        .is_none_or(|s| s.trim().is_empty())
    {
        return Err("ET_NETWORK_REQUIRED");
    }
    if (doc.get("ipv4").is_some() && cfg.get_ipv4().is_none())
        || (doc.get("ipv6").is_some() && cfg.get_ipv6().is_none())
    {
        return Err("ET_ADDRESS_INVALID");
    }
    if cfg.get_ipv4().is_some_and(|ip| ip.network_length() == 0)
        || cfg.get_ipv6().is_some_and(|ip| ip.network_length() == 0)
    {
        return Err("ET_DEFAULT_ROUTE_FORBIDDEN");
    }
    cfg.set_id(id); // persistent phone identity is supplied separately from imported TOML
    cfg.set_inst_name("cmfa-active-mesh".to_owned());
    Ok(cfg)
}

fn text(env: &mut JNIEnv, value: &JString) -> Result<String, &'static str> {
    env.get_string(value)
        .map(Into::into)
        .map_err(|_| "ET_JNI_STRING")
}
fn fail(env: &mut JNIEnv, code: &'static str) {
    let _ = env.throw_new("java/lang/IllegalStateException", code);
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_github_kr328_clash_core_easytier_NativeEasyTier_validate(
    mut env: JNIEnv,
    _this: JObject,
    toml: JString,
) -> jboolean {
    match text(&mut env, &toml).and_then(|s| config(&s, uuid::Uuid::nil())) {
        Ok(_) => 1,
        Err(e) => {
            fail(&mut env, e);
            0
        }
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_github_kr328_clash_core_easytier_NativeEasyTier_start(
    mut env: JNIEnv,
    _this: JObject,
    toml: JString,
    phone_id: JString,
    generation: jlong,
    transport_isolated: jboolean,
) -> jboolean {
    // Until the host proves its outer sockets bypass the VPN, starting is unsafe.
    if transport_isolated != 1 || generation <= 0 {
        fail(&mut env, "ET_TRANSPORT_NOT_ISOLATED");
        return 0;
    }
    let result = (|| {
        let id = uuid::Uuid::parse_str(&text(&mut env, &phone_id)?)
            .map_err(|_| "ET_PHONE_ID_INVALID")?;
        if id.is_nil() {
            return Err("ET_PHONE_ID_INVALID");
        }
        let cfg = config(&text(&mut env, &toml)?, id)?;
        let mut slot = SESSION.lock().map_err(|_| "ET_STATE_UNAVAILABLE")?;
        if slot.is_some() {
            return Err("ET_ALREADY_RUNNING");
        }
        let configured_ipv6 = cfg.get_ipv6().map(|ip| ip.to_string());
        let manager = NetworkInstanceManager::new();
        manager
            .run_network_instance(cfg, false, ConfigFileControl::STATIC_CONFIG)
            .map_err(|_| "ET_START_FAILED")?;
        *slot = Some(Session {
            generation,
            id,
            manager,
            configured_ipv6,
            packet_ready: false,
            #[cfg(unix)]
            packet: None,
        });
        Ok(())
    })();
    match result {
        Ok(()) => 1,
        Err(e) => {
            fail(&mut env, e);
            0
        }
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_github_kr328_clash_core_easytier_NativeEasyTier_attachPacketFd(
    mut env: JNIEnv,
    _this: JObject,
    generation: jlong,
    fd: jint,
) -> jboolean {
    #[cfg(target_os = "android")]
    let result = (|| {
        let mut slot = SESSION.lock().map_err(|_| "ET_STATE_UNAVAILABLE")?;
        let session = slot
            .as_mut()
            .filter(|s| s.generation == generation)
            .ok_or("ET_STALE_SESSION")?;
        if session.packet.is_some() || fd < 0 {
            return Err("ET_PACKET_FD_INVALID");
        }
        let mut socket_type: libc::c_int = 0;
        let mut len = std::mem::size_of::<libc::c_int>() as libc::socklen_t;
        // Only a datagram packet pair is accepted, never a second Android TUN.
        let rc = unsafe {
            libc::getsockopt(
                fd,
                libc::SOL_SOCKET,
                libc::SO_TYPE,
                (&mut socket_type as *mut libc::c_int).cast(),
                &mut len,
            )
        };
        if rc != 0 || socket_type != libc::SOCK_DGRAM {
            return Err("ET_PACKET_FD_INVALID");
        }
        let mut address: libc::sockaddr_storage = unsafe { std::mem::zeroed() };
        let mut address_len = std::mem::size_of::<libc::sockaddr_storage>() as libc::socklen_t;
        let rc = unsafe {
            libc::getsockname(
                fd,
                (&mut address as *mut libc::sockaddr_storage).cast(),
                &mut address_len,
            )
        };
        if rc != 0 || address.ss_family as i32 != libc::AF_UNIX {
            return Err("ET_PACKET_FD_INVALID");
        }
        let duplicate = unsafe { libc::fcntl(fd, libc::F_DUPFD_CLOEXEC, 0) };
        if duplicate < 0 {
            return Err("ET_PACKET_FD_INVALID");
        }
        let owned = unsafe { OwnedFd::from_raw_fd(duplicate) };
        let mut events = session
            .manager
            .iter()
            .find(|instance| *instance.key() == session.id)
            .and_then(|instance| instance.subscribe_event())
            .ok_or("ET_STATUS_UNAVAILABLE")?;
        // Keep the descriptor owned even on a timeout: native code may still be
        // attaching it. Session shutdown joins workers before closing this FD.
        session.packet = Some(owned);
        session
            .manager
            .set_tun_fd(&session.id, duplicate)
            .map_err(|_| "ET_ATTACH_FAILED")?;
        let expected = format!("tunfd_{duplicate}");
        let start = std::time::Instant::now();
        while start.elapsed() < std::time::Duration::from_secs(5) {
            if let Ok(event) = events.try_recv()
                && packet_event(event, &expected)?
            {
                session.packet_ready = true;
                return Ok(());
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
        Err("ET_PACKET_DEVICE_TIMEOUT")
    })();
    #[cfg(not(target_os = "android"))]
    let result: Result<(), &'static str> = {
        let _ = (generation, fd);
        Err("ET_ANDROID_REQUIRED")
    };
    match result {
        Ok(()) => 1,
        Err(e) => {
            fail(&mut env, e);
            0
        }
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_github_kr328_clash_core_easytier_NativeEasyTier_snapshot(
    mut env: JNIEnv,
    _this: JObject,
    generation: jlong,
) -> jstring {
    let result = (|| {
        let slot = SESSION.lock().map_err(|_| "ET_STATE_UNAVAILABLE")?;
        let session = slot
            .as_ref()
            .filter(|s| s.generation == generation)
            .ok_or("ET_STALE_SESSION")?;
        let infos = session
            .manager
            .collect_network_infos_sync()
            .map_err(|_| "ET_STATUS_UNAVAILABLE")?;
        let info = infos.get(&session.id).ok_or("ET_STATUS_UNAVAILABLE")?;
        // Deliberately omit raw config, events, public endpoints and network secret.
        let mut addresses = Vec::new();
        if let Some(ip) = info
            .my_node_info
            .as_ref()
            .and_then(|n| n.virtual_ipv4.as_ref())
        {
            if ip.network_length == 0 || ip.network_length > 32 || ip.address.is_none() {
                return Err("ET_STATUS_INVALID");
            }
            addresses.push(format!("{}/{}", ip.address.unwrap(), ip.network_length));
        }
        if let Some(ip) = &session.configured_ipv6 {
            addresses.push(ip.clone());
        }
        let mut routes = std::collections::BTreeSet::new();
        for route in &info.routes {
            if let Some(ip) = route.ipv4_addr.as_ref().and_then(|ip| ip.address) {
                routes.insert(format!("{ip}/32"));
            }
            if let Some(ip) = route.ipv6_addr.as_ref().and_then(|ip| ip.address) {
                routes.insert(format!("{ip}/128"));
            }
            for prefix in &route.proxy_cidrs {
                routes.insert(prefix.clone());
            }
            if routes.len() > 4096 {
                return Err("ET_STATUS_TOO_LARGE");
            }
        }
        #[cfg(unix)]
        let attached = session.packet.is_some() && session.packet_ready;
        #[cfg(not(unix))]
        let attached = false;
        Ok(json!({"schema":1,"generation":generation,"running":info.running && info.error_msg.is_none(),"attached":attached,"addresses":addresses,"routes":routes}).to_string())
    })();
    match result {
        Ok(value) => match env.new_string(value) {
            Ok(s) => s.into_raw(),
            Err(_) => {
                fail(&mut env, "ET_JNI_STRING");
                ptr::null_mut()
            }
        },
        Err(e) => {
            fail(&mut env, e);
            ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_github_kr328_clash_core_easytier_NativeEasyTier_stop(
    mut env: JNIEnv,
    _this: JObject,
    generation: jlong,
) {
    match SESSION.lock() {
        Ok(mut slot) => {
            if slot.as_ref().is_some_and(|s| s.generation != generation) {
                fail(&mut env, "ET_STALE_SESSION");
                return;
            }
            drop(slot.take()); // joins native workers before closing the packet descriptor
        }
        Err(_) => fail(&mut env, "ET_STATE_UNAVAILABLE"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn attachment_requires_matching_native_event_and_redacts_errors() {
        assert_eq!(
            packet_event(GlobalCtxEvent::TunDeviceReady("tunfd_9".into()), "tunfd_9"),
            Ok(true)
        );
        assert_eq!(
            packet_event(GlobalCtxEvent::TunDeviceReady("tunfd_8".into()), "tunfd_9"),
            Ok(false)
        );
        assert_eq!(
            packet_event(
                GlobalCtxEvent::TunDeviceError("private-native-error".into()),
                "tunfd_9"
            ),
            Err("ET_PACKET_DEVICE_FAILED")
        );
    }
    #[test]
    fn errors_are_fixed_codes() {
        let secret = "do-not-print-this-network-secret";
        let e = config(&format!("invalid={secret}"), uuid::Uuid::nil())
            .err()
            .unwrap();
        assert_eq!(e, "ET_CONFIG_SYNTAX");
        assert!(!e.contains(secret));
    }
    #[test]
    fn host_paths_and_portals_rejected() {
        for key in [
            "credential_file",
            "file_logger",
            "rpc_portal",
            "netns",
            "socks5_proxy",
            "vpn_portal_config",
            "source",
            "proxy_network",
        ] {
            assert_eq!(
                config(&format!("{key}='test'"), uuid::Uuid::nil()).err(),
                Some("ET_UNSUPPORTED_HOST_OPTION")
            );
        }
    }
    #[test]
    fn rejects_no_tun_outbound_substitution() {
        assert_eq!(
            config("[flags]\nno_tun=true", uuid::Uuid::nil()).err(),
            Some("ET_PACKET_DEVICE_REQUIRED")
        );
    }
    #[test]
    fn malformed_flags_cannot_reach_upstream_unwrap() {
        for flags in [
            "mtu='secret-value'",
            "enable_ipv6='true'",
            "mtu=-1",
            "multi_thread_count=[]",
        ] {
            assert_eq!(
                config(&format!("[flags]\n{flags}"), uuid::Uuid::nil()).err(),
                Some("ET_FLAGS_INVALID")
            );
        }
        assert_eq!(
            config("[flags]\nmisspelled_option=true", uuid::Uuid::nil()).err(),
            Some("ET_FLAG_UNKNOWN")
        );
        assert_eq!(
            config("[flags]\nmtu=9000", uuid::Uuid::nil()).err(),
            Some("ET_MTU_INVALID")
        );
    }
    #[test]
    fn requires_explicit_mesh_identity_and_valid_addresses() {
        assert_eq!(
            config("dhcp=true", uuid::Uuid::nil()).err(),
            Some("ET_NETWORK_REQUIRED")
        );
        let good = "ipv4='10.126.0.2/24'\n[network_identity]\nnetwork_name='test-only'\nnetwork_secret='fixture-only'";
        assert!(config(good, uuid::Uuid::nil()).is_ok());
        assert_eq!(
            config(&good.replace("10.126.0.2/24", "invalid"), uuid::Uuid::nil()).err(),
            Some("ET_ADDRESS_INVALID")
        );
    }
}
