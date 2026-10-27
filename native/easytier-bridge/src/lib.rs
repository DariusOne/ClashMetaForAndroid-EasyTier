//! Native EasyTier adapter. No VpnService, interface creation or config logging.
//! Android supplies an owned packet endpoint after establishing transport
//! isolation. This crate is not yet enabled in the production service.

use easytier::{
    common::config::{ConfigFileControl, ConfigLoader, TomlConfigLoader},
    instance_manager::NetworkInstanceManager,
};
use jni::{
    JNIEnv,
    objects::{JObject, JString},
    sys::{jboolean, jint, jlong, jstring},
};
use serde_json::json;
use std::{ptr, sync::{LazyLock, Mutex}};
#[cfg(unix)]
use std::os::fd::{FromRawFd, OwnedFd, AsRawFd};

const MAX_CONFIG_BYTES: usize = 1024 * 1024;

struct Session {
    generation: i64,
    id: uuid::Uuid,
    // Drop the engine (which joins its workers) BEFORE the borrowed packet fd.
    manager: NetworkInstanceManager,
    #[cfg(unix)]
    packet: Option<OwnedFd>,
}

impl Drop for Session {
    fn drop(&mut self) {
        let _ = self.manager.retain_network_instance(Vec::new());
    }
}

static SESSION: LazyLock<Mutex<Option<Session>>> = LazyLock::new(|| Mutex::new(None));

// Failures use fixed codes; upstream parser errors may contain passwords/URIs.
fn config(text: &str, id: uuid::Uuid) -> Result<TomlConfigLoader, &'static str> {
    if text.len() > MAX_CONFIG_BYTES || text.is_empty() { return Err("ET_CONFIG_SIZE"); }
    let doc: toml::Value = toml::from_str(text).map_err(|_| "ET_CONFIG_SYNTAX")?;
    // No file imports, management portals or host routing from a mobile profile.
    for key in ["credential_file", "rpc_portal", "socks5_portal", "vpn_portal", "port_forward", "port_forwards", "netns", "file_logger"] {
        if doc.get(key).is_some() { return Err("ET_UNSUPPORTED_HOST_OPTION"); }
    }
    let cfg = TomlConfigLoader::new_from_str(text).map_err(|_| "ET_CONFIG_INVALID")?;
    if !cfg.get_exit_nodes().is_empty() || cfg.get_routes().unwrap_or_default().iter().any(|r| r.network_length() == 0) {
        return Err("ET_DEFAULT_ROUTE_FORBIDDEN");
    }
    if cfg.get_flags().no_tun || cfg.get_flags().use_smoltcp {
        return Err("ET_PACKET_DEVICE_REQUIRED");
    }
    if cfg.get_network_identity().network_name.trim().is_empty() { return Err("ET_NETWORK_REQUIRED"); }
    cfg.set_id(id); // persistent phone identity is supplied separately from imported TOML
    cfg.set_inst_name("cmfa-active-mesh".to_owned());
    Ok(cfg)
}

fn text(env: &mut JNIEnv, value: &JString) -> Result<String, &'static str> {
    env.get_string(value).map(Into::into).map_err(|_| "ET_JNI_STRING")
}
fn fail(env: &mut JNIEnv, code: &'static str) { let _ = env.throw_new("java/lang/IllegalStateException", code); }

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_github_kr328_clash_core_easytier_NativeEasyTier_validate(
    mut env: JNIEnv, _this: JObject, toml: JString,
) -> jboolean {
    match text(&mut env, &toml).and_then(|s| config(&s, uuid::Uuid::nil())) {
        Ok(_) => 1,
        Err(e) => { fail(&mut env,e); 0 }
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_github_kr328_clash_core_easytier_NativeEasyTier_start(
    mut env: JNIEnv, _this: JObject, toml: JString, phone_id: JString,
    generation: jlong, transport_isolated: jboolean,
) -> jboolean {
    // Until the host proves its outer sockets bypass the VPN, starting is unsafe.
    if transport_isolated != 1 || generation <= 0 { fail(&mut env,"ET_TRANSPORT_NOT_ISOLATED"); return 0; }
    let result = (|| {
        let id = uuid::Uuid::parse_str(&text(&mut env,&phone_id)?).map_err(|_| "ET_PHONE_ID_INVALID")?;
        if id.is_nil() { return Err("ET_PHONE_ID_INVALID"); }
        let cfg = config(&text(&mut env,&toml)?, id)?;
        let mut slot = SESSION.lock().map_err(|_| "ET_STATE_UNAVAILABLE")?;
        if slot.is_some() { return Err("ET_ALREADY_RUNNING"); }
        let manager = NetworkInstanceManager::new();
        manager.run_network_instance(cfg, false, ConfigFileControl::STATIC_CONFIG).map_err(|_| "ET_START_FAILED")?;
        *slot = Some(Session { generation, id, manager, #[cfg(unix)] packet: None });
        Ok(())
    })();
    match result { Ok(()) => 1, Err(e) => { fail(&mut env,e); 0 } }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_github_kr328_clash_core_easytier_NativeEasyTier_attachPacketFd(
    mut env: JNIEnv, _this: JObject, generation: jlong, fd: jint,
) -> jboolean {
    #[cfg(target_os = "android")]
    let result = (|| {
        let mut slot = SESSION.lock().map_err(|_| "ET_STATE_UNAVAILABLE")?;
        let session = slot.as_mut().filter(|s| s.generation == generation).ok_or("ET_STALE_SESSION")?;
        if session.packet.is_some() || fd < 0 { return Err("ET_PACKET_FD_INVALID"); }
        let mut socket_type: libc::c_int = 0;
        let mut len = std::mem::size_of::<libc::c_int>() as libc::socklen_t;
        // Only a datagram packet pair is accepted, never a second Android TUN.
        let rc = unsafe { libc::getsockopt(fd,libc::SOL_SOCKET,libc::SO_TYPE,(&mut socket_type as *mut libc::c_int).cast(),&mut len) };
        if rc != 0 || socket_type != libc::SOCK_DGRAM { return Err("ET_PACKET_FD_INVALID"); }
        let mut address: libc::sockaddr_storage = unsafe { std::mem::zeroed() };
        let mut address_len = std::mem::size_of::<libc::sockaddr_storage>() as libc::socklen_t;
        let rc = unsafe { libc::getsockname(fd,(&mut address as *mut libc::sockaddr_storage).cast(),&mut address_len) };
        if rc != 0 || address.ss_family as i32 != libc::AF_UNIX { return Err("ET_PACKET_FD_INVALID"); }
        let duplicate = unsafe { libc::fcntl(fd,libc::F_DUPFD_CLOEXEC,0) };
        if duplicate < 0 { return Err("ET_PACKET_FD_INVALID"); }
        let owned = unsafe { OwnedFd::from_raw_fd(duplicate) };
        session.manager.set_tun_fd(&session.id,owned.as_raw_fd()).map_err(|_| "ET_ATTACH_FAILED")?;
        session.packet = Some(owned);
        Ok(())
    })();
    #[cfg(not(target_os = "android"))]
    let result: Result<(), &'static str> = { let _ = (generation,fd); Err("ET_ANDROID_REQUIRED") };
    match result { Ok(()) => 1, Err(e) => { fail(&mut env,e); 0 } }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_github_kr328_clash_core_easytier_NativeEasyTier_snapshot(
    mut env: JNIEnv, _this: JObject, generation: jlong,
) -> jstring {
    let result = (|| {
        let slot = SESSION.lock().map_err(|_| "ET_STATE_UNAVAILABLE")?;
        let session = slot.as_ref().filter(|s| s.generation == generation).ok_or("ET_STALE_SESSION")?;
        let infos = session.manager.collect_network_infos_sync().map_err(|_| "ET_STATUS_UNAVAILABLE")?;
        let info = infos.get(&session.id).ok_or("ET_STATUS_UNAVAILABLE")?;
        // Deliberately omit raw config, events, public endpoints and network secret.
        let routes: Vec<_> = info.routes.iter().map(|r| json!({"ipv4":r.ipv4_addr,"ipv6":r.ipv6_addr,"proxy_cidrs":r.proxy_cidrs})).collect();
        Ok(json!({"generation":generation,"running":info.running && info.error_msg.is_none(),"ipv4":info.my_node_info.as_ref().and_then(|n|n.virtual_ipv4.as_ref()),"routes":routes}).to_string())
    })();
    match result {
        Ok(value) => match env.new_string(value) { Ok(s) => s.into_raw(), Err(_) => { fail(&mut env,"ET_JNI_STRING"); ptr::null_mut() } },
        Err(e) => { fail(&mut env,e); ptr::null_mut() }
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_github_kr328_clash_core_easytier_NativeEasyTier_stop(
    mut env: JNIEnv, _this: JObject, generation: jlong,
) {
    match SESSION.lock() {
        Ok(mut slot) => {
            if slot.as_ref().is_some_and(|s|s.generation != generation) { fail(&mut env,"ET_STALE_SESSION"); return; }
            drop(slot.take()); // joins native workers before closing the packet descriptor
        }
        Err(_) => fail(&mut env,"ET_STATE_UNAVAILABLE")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn errors_are_fixed_codes() {
        let secret = "do-not-print-this-network-secret";
        let e = config(&format!("invalid={secret}"),uuid::Uuid::nil()).err().unwrap();
        assert_eq!(e,"ET_CONFIG_SYNTAX");assert!(!e.contains(secret));
    }
    #[test]
    fn host_paths_and_portals_rejected() {
        for key in ["credential_file","file_logger","rpc_portal","netns"] {
            assert_eq!(config(&format!("{key}='test'"),uuid::Uuid::nil()).err(),Some("ET_UNSUPPORTED_HOST_OPTION"));
        }
    }
    #[test]
    fn rejects_no_tun_outbound_substitution() {
        assert_eq!(config("[flags]\nno_tun=true",uuid::Uuid::nil()).err(),Some("ET_PACKET_DEVICE_REQUIRED"));
    }
}
