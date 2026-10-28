#!/usr/bin/env python3
"""Real packet probes on disposable CI Linux/Android peers, never a user's mesh.

Android probes run under shell UID, which is captured by the prototype's VPN.
The VPN application's own UID is excluded and cannot prove application capture.
Results describe this emulator only; DNS, discovery and real phones remain gates.
"""
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile
from fixture_file_stage import atomic_stage_script
from fixture_transition_watch import TransitionWatch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "com.github.metacubex.clash.meshprototype.meta"
FOLDER = "no_backup/native-mesh-acceptance/"
CORE_URL = "https://github.com/EasyTier/EasyTier/releases/download/v2.6.4/easytier-linux-x86_64-v2.6.4.zip"
CORE_SHA = "61b659eaedba658fa66fe47d17e1426cdd77e5d02fa15fed447bb4357c09dfd6"


class Echo:
    def __init__(self, udp):
        self.udp = udp
        self.socket = socket.socket(type=socket.SOCK_DGRAM if udp else socket.SOCK_STREAM)
        self.socket.bind(("0.0.0.0", 0))
        self.port = self.socket.getsockname()[1]
        self.sources = []
        self.done = threading.Event()
        if not udp:
            self.socket.listen(16)
        self.socket.settimeout(0.5)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.done.is_set():
            try:
                if self.udp:
                    data, peer = self.socket.recvfrom(4096)
                    self.sources.append(peer[0])
                    self.socket.sendto(data, peer)
                else:
                    conn, peer = self.socket.accept()
                    # Count the TCP accept itself, even if no payload follows.
                    # Otherwise a leaked connection with an empty/slow body
                    # could falsely satisfy the REJECT zero-origin assertion.
                    self.sources.append(peer[0])
                    with conn:
                        conn.settimeout(5)
                        data = b""
                        while not data.endswith(b"\n") and len(data) < 128:
                            chunk = conn.recv(128 - len(data))
                            if not chunk:
                                break
                            data += chunk
                        conn.sendall(data)
            except (TimeoutError, OSError):
                if self.done.is_set():
                    break

    def close(self):
        self.done.set()
        self.socket.close()
        self.thread.join(2)


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.name != "posix":
        raise RuntimeError("Disposable Linux CI only")
    devices = subprocess.check_output(["adb", "devices"], text=True)
    serials = re.findall(r"^(emulator-\d+)\s+device$", devices, re.M)
    if len(serials) != 1:
        raise RuntimeError("Exactly one CI emulator required")
    adb = ["adb", "-s", serials[0]]

    def call(*args, timeout=30):
        return subprocess.check_output(adb + list(args), text=True, stderr=subprocess.STDOUT, timeout=timeout)

    if call("shell", "getprop", "ro.kernel.qemu").strip() != "1":
        raise RuntimeError("Real devices are forbidden by this fixture")

    def stage(name, data):
        command = shlex.quote(atomic_stage_script(name))
        subprocess.run(adb + ["shell", "-T", "run-as", PACKAGE, "sh", "-c", command], input=data.encode(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=15)

    report = ROOT / "app/build/reports/native-mesh-peer"
    report.mkdir(parents=True, exist_ok=True)
    result = {"kind": "disposable-emulator-real-native-peer", "passed": False,
              "real_device_validated": False, "complete_integration": False,
              "dns_fakeip_validated": False, "discovery_validated": False, "checks": {}}
    peer = instrument = instrumentation = capture = None
    helpers = []
    transition_watches = []
    with tempfile.TemporaryDirectory(prefix="cmfa-native-peer-") as temp, ExitStack() as stack:
        temp = Path(temp)
        os.chmod(temp, 0o700)
        try:
            with urllib.request.urlopen(CORE_URL, timeout=60) as response:
                archive = response.read(100 * 1024 * 1024 + 1)
            if len(archive) > 100 * 1024 * 1024 or hashlib.sha256(archive).hexdigest() != CORE_SHA:
                raise RuntimeError("Pinned peer archive mismatch")
            core = temp / "easytier-core"
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                candidates = [n for n in bundle.namelist() if n.endswith("/easytier-core") or n == "easytier-core"]
                if len(candidates) != 1:
                    raise RuntimeError("Peer executable missing")
                core.write_bytes(bundle.read(candidates[0]))
            core.chmod(0o700)
            sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ["ANDROID_HOME"])
            clang = sdk / "ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin/x86_64-linux-android21-clang"
            probe = temp / "cmfa-mesh-probe"
            subprocess.run([str(clang), "-Wall", "-Wextra", "-Werror", "-O2", str(ROOT / "scripts/fixtures/mesh_probe.c"), "-o", str(probe)], check=True)
            call("push", str(probe), "/data/local/tmp/cmfa-mesh-probe")
            call("shell", "chmod", "700", "/data/local/tmp/cmfa-mesh-probe")
            transition = temp / "cmfa-transition-probe"
            subprocess.run(["go", "build", "-trimpath", "-o", str(transition), str(ROOT / "scripts/fixtures/transition_probe.go")],
                           env={**os.environ, "GOOS":"linux", "GOARCH":"amd64", "CGO_ENABLED":"0"},check=True)
            call("push", str(transition), "/data/local/tmp/cmfa-transition-probe")
            call("shell", "chmod", "700", "/data/local/tmp/cmfa-transition-probe")
            with socket.socket() as reserve:
                reserve.bind(("127.0.0.1", 0))
                port = reserve.getsockname()[1]
            token = uuid.uuid4().hex
            identity = f"[network_identity]\nnetwork_name='ci-{token}'\nnetwork_secret='{token}'\n"
            host_config = temp / "peer.toml"
            host_config.write_text(f"ipv4='10.126.0.1/24'\ndhcp=false\nlisteners=['tcp://127.0.0.1:{port}']\nstun_servers=[]\nstun_servers_v6=[]\n" + identity + "[flags]\nmtu=1380\ndev_name='ci-et-peer'\nenable_ipv6=false\ndisable_p2p=true\n")
            host_config.chmod(0o600)
            peer_log = stack.enter_context((temp / "peer-private.log").open("wb"))
            peer = subprocess.Popen(["sudo", "--", str(core), "--config-file", str(host_config)], stdout=peer_log, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if peer.poll() is not None:
                    raise RuntimeError("Pinned native peer exited")
                status = subprocess.run(["ip", "-j", "address", "show", "dev", "ci-et-peer"], capture_output=True, text=True)
                if status.returncode == 0 and "10.126.0.1" in status.stdout:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("Native peer interface not ready")
            # Disposable CI only: capture headers on the synthetic mesh NIC,
            # never the encrypted underlay, credentials or packet payloads.
            # A finite packet count bounds this diagnostic even on test failure.
            packet_log = stack.enter_context((report / "mesh-packet-headers.txt").open("w"))
            capture = subprocess.Popen(["sudo", "-n", "tcpdump", "-n", "-l", "-tt", "-i", "ci-et-peer", "-c", "2000",
                                        "net 10.126.0.0/24 and (tcp or udp)"], stdout=packet_log, stderr=subprocess.STDOUT, start_new_session=True)
            phone = f"ipv4='10.126.0.2/24'\ndhcp=false\nlisteners=[]\nstun_servers=[]\nstun_servers_v6=[]\n[[peer]]\nuri='tcp://10.0.2.2:{port}'\n" + identity + "[flags]\nmtu=1380\nenable_ipv6=false\ndisable_p2p=true\n"
            stage("mesh.toml", phone)
            stage("ci-peer-guard", "disposable-ci-only")
            reject = Echo(False)
            stack.callback(reject.close)
            stage("ci-reject-port", str(reject.port))
            instrumentation = stack.enter_context((report / "instrumentation.txt").open("w"))
            instrument = subprocess.Popen(adb + ["shell", "am", "instrument", "-w", "-r", "-e", "disposableEmulator", "true", "-e", "class", "com.github.kr328.clash.NativeMeshPeerTest", PACKAGE + ".test/androidx.test.runner.AndroidJUnitRunner"], stdout=instrumentation, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 75
            while time.monotonic() < deadline:
                if instrument.poll() is not None:
                    raise RuntimeError("Android peer harness did not start")
                ready = subprocess.run(adb + ["shell", "run-as", PACKAGE, "cat", FOLDER + "peer-ready"], capture_output=True, text=True, timeout=10)
                if ready.returncode == 0 and ready.stdout.strip() == "ready":
                    break
                time.sleep(0.3)
            else:
                raise RuntimeError("Android peer harness startup timed out")
            # Native route exchange is asynchronous. Use a bounded readiness
            # ping separately; it does not count as one of the five assertions.
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                ping = subprocess.run(["ping", "-n", "-c", "1", "-W", "1", "10.126.0.2"], capture_output=True)
                if ping.returncode == 0:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("Native peer route handshake failed")
            for mode in ("tcp", "udp"):
                echo = Echo(mode == "udp")
                stack.callback(echo.close)
                for label, address in (("mesh", "10.126.0.1"), ("nonmesh_clash", "10.0.2.2")):
                    before = len(echo.sources)
                    output = call("shell", "/data/local/tmp/cmfa-mesh-probe", mode + "-client", address, str(echo.port), timeout=60)
                    sources = echo.sources[before:]
                    if "PASS 5/5" not in output or len(sources) != 5 or any((ip == "10.126.0.2") != (label == "mesh") for ip in sources):
                        raise RuntimeError("Packet/source assertion failed: " + label + "_" + mode)
                    result["checks"][label + "_outbound_" + mode] = {"passed": 5, "expected": 5, "sources_verified": True}
            denied = subprocess.run(adb + ["shell", "/data/local/tmp/cmfa-mesh-probe", "tcp-client", "10.0.2.2", str(reject.port)], capture_output=True, text=True, timeout=20)
            if denied.returncode == 0 or reject.sources:
                raise RuntimeError("Original nonmesh REJECT rule was bypassed")
            result["checks"]["nonmesh_original_reject_rule"] = {"passed": True, "origin_connections": 0}
            # Match real CMFA modes without changing the native mesh session.
            # Global uses REJECT deliberately: only unrelated destinations
            # should be rejected, while mesh TCP still takes native EasyTier.
            for sequence, mode in enumerate(("direct", "global", "rule"), 1):
                stage("mode-request.json", json.dumps({"sequence": sequence, "mode": mode}))
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    state = subprocess.run(adb + ["shell", "run-as", PACKAGE, "cat", FOLDER + "mode-ready.json"], capture_output=True, text=True, timeout=10)
                    try:
                        ready_sequence = json.loads(state.stdout).get("sequence")
                    except (ValueError, AttributeError):
                        ready_sequence = None
                    if state.returncode == 0 and ready_sequence == sequence:
                        break
                    time.sleep(0.2)
                else:
                    raise RuntimeError("Original CMFA mode did not apply: " + mode)
                echo = Echo(False)
                stack.callback(echo.close)
                output = call("shell", "/data/local/tmp/cmfa-mesh-probe", "tcp-client", "10.126.0.1", str(echo.port), timeout=60)
                if "PASS 5/5" not in output or echo.sources != ["10.126.0.2"] * 5:
                    raise RuntimeError("Mesh path changed with CMFA mode: " + mode)
                before = len(reject.sources)
                probe = subprocess.run(adb + ["shell", "/data/local/tmp/cmfa-mesh-probe", "tcp-client", "10.0.2.2", str(reject.port)], capture_output=True, text=True, timeout=30)
                if mode == "direct":
                    if probe.returncode or "PASS 5/5" not in probe.stdout or len(reject.sources) != before + 5 or "10.126.0.2" in reject.sources[before:]:
                        raise RuntimeError("CMFA Direct behavior changed")
                elif probe.returncode == 0 or len(reject.sources) != before:
                    raise RuntimeError("CMFA rejection bypassed: " + mode)
                result["checks"]["mode_" + mode] = {"mesh_tcp": "5/5", "nonmesh_expected": "direct" if mode == "direct" else "reject", "passed": True}
            for mode, port in (("tcp", 27441), ("udp", 27442)):
                helper = subprocess.Popen(adb + ["shell", "/data/local/tmp/cmfa-mesh-probe", mode + "-server", "0.0.0.0", str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                helpers.append(helper)
                ready = threading.Event()
                first = []
                def read_ready():
                    first.append(helper.stdout.readline().strip())
                    ready.set()
                threading.Thread(target=read_ready, daemon=True).start()
                if not ready.wait(15) or first != ["READY"]:
                    raise RuntimeError("Phone listener not ready")
                for i in range(5):
                    with socket.socket(type=socket.SOCK_DGRAM if mode == "udp" else socket.SOCK_STREAM) as client:
                        client.settimeout(8)
                        client.connect(("10.126.0.2", port))
                        request = ("reverse-packet-" + str(i) + "\n").encode()
                        client.sendall(request)
                        response = b""
                        while len(response) < len(request):
                            chunk = client.recv(128)
                            if not chunk:
                                break
                            response += chunk
                        if response != request:
                            raise RuntimeError("Reverse packet payload mismatch")
                output = helper.communicate(timeout=15)[0]
                if helper.returncode or "PASS 5/5" not in output:
                    raise RuntimeError("Phone listener failed")
                result["checks"]["mesh_inbound_" + mode] = {"passed": 5, "expected": 5}
            for direction, command in (("outbound", adb + ["shell", "ping", "-n", "-c", "5", "-W", "2", "10.126.0.1"]), ("inbound", ["ping", "-n", "-c", "5", "-W", "2", "10.126.0.2"])):
                ping = subprocess.run(command, capture_output=True, text=True, timeout=20)
                if ping.returncode or not re.search(r"5 (?:packets )?received", ping.stdout):
                    raise RuntimeError("ICMP roundtrip failed: " + direction)
                result["checks"]["mesh_" + direction + "_icmp"] = {"passed": 5, "expected": 5}
            original = json.loads(call("shell", "run-as", PACKAGE, "cat", FOLDER + "status.json"))
            rebuilds = []
            result["checks"]["interface_rebuilds"] = rebuilds
            for sequence in range(1, 4):
                cycle = {"cycle": sequence, "passed": False, "protocols": {}}
                rebuilds.append(cycle)
                watches = []
                for mode in ("tcp", "udp"):
                    echo = Echo(mode == "udp")
                    stack.callback(echo.close)
                    watch = TransitionWatch(adb + ["shell", "/data/local/tmp/cmfa-transition-probe", mode, str(echo.port)])
                    transition_watches.append(watch)
                    watches.append((mode,echo,watch))
                for _,_,watch in watches: watch.ready()
                stage("rebuild-request", str(sequence))
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    state = json.loads(call("shell", "run-as", PACKAGE, "cat", FOLDER + "status.json"))
                    if state.get("stage") == "active" and state.get("rebuild_request") == sequence:
                        break
                    if state.get("stage", "").startswith("ET_"):
                        raise RuntimeError("Interface rebuild failed")
                    time.sleep(.2)
                else:
                    raise RuntimeError("Interface rebuild timed out")
                if state["generation"] != original["generation"] or state["interface_revision"] <= original["interface_revision"]:
                    raise RuntimeError("Rebuild replaced mesh session or did not replace interface")
                cycle["session_preserved"] = True
                cycle["interface_revision"] = state["interface_revision"]
                cycle["transition"] = {}
                covered = all(w.process.poll() is None for _,_,w in watches)
                for mode,echo,watch in watches:
                    cycle["transition"][mode] = watch.finish(lambda echo=echo:list(echo.sources))
                cycle["transition_covered_ready"] = covered
                if not covered or not all(x["passed"] for x in cycle["transition"].values()):
                    raise RuntimeError("Continuous handover packet/source assertion failed")
                for mode in ("tcp", "udp"):
                    echo = Echo(mode == "udp")
                    stack.callback(echo.close)
                    probe = subprocess.run(adb + ["shell", "/data/local/tmp/cmfa-mesh-probe", mode + "-client", "10.126.0.1", str(echo.port)],
                                           capture_output=True, text=True, timeout=60)
                    output = probe.stdout + probe.stderr
                    sources = list(echo.sources)
                    # Preserve bounded, credential-free diagnostics BEFORE the
                    # assertion. A later failure must not erase earlier cycles
                    # or conflate payload failure with incorrect source routing.
                    cycle["protocols"][mode] = {
                        "returncode": probe.returncode,
                        "fixture_port": echo.port,
                        "probe_codes": [line for line in output.splitlines() if re.fullmatch(r"[A-Z_]+(?: [0-5])?", line)],
                        "payload_5_of_5": "PASS 5/5" in output,
                        "observed": len(sources),
                        "mesh_sources": sources.count("10.126.0.2"),
                        "clash_gateway_sources": sources.count("172.19.0.1"),
                        "other_sources": sum(ip not in ("10.126.0.2", "172.19.0.1") for ip in sources),
                    }
                    if probe.returncode or "PASS 5/5" not in output or sources != ["10.126.0.2"] * 5:
                        raise RuntimeError("Mesh rebuild packet/source assertion failed: " + mode)
                ping = subprocess.run(["ping", "-n", "-c", "5", "-W", "2", "10.126.0.2"], capture_output=True, text=True, timeout=20)
                if ping.returncode or not re.search(r"5 (?:packets )?received", ping.stdout):
                    raise RuntimeError("Inbound packets did not recover after rebuild")
                cycle.update({"passed": True, "outbound_tcp": "5/5", "outbound_udp": "5/5", "inbound_icmp": "5/5"})
                original = state
            stage("peer-result.json", '{"passed":true}')
            instrument.wait(timeout=30)
            instrumentation.flush()
            text = (report / "instrumentation.txt").read_text()
            if instrument.returncode or "OK (1 test)" not in text or "FAILURES!!!" in text:
                raise RuntimeError("Android peer lifecycle assertion failed")
            result["passed"] = True
        finally:
            for watch in transition_watches: watch.close()
            if not result["passed"]:
                try:
                    stage("peer-result.json", '{"passed":false}')
                except Exception:
                    pass
            for child in helpers + ([instrument] if instrument else []):
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
            if capture is not None and capture.poll() is None:
                subprocess.run(["sudo", "kill", "-TERM", "--", "-" + str(capture.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    capture.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    subprocess.run(["sudo", "kill", "-KILL", "--", "-" + str(capture.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    capture.wait(timeout=5)
            if peer is not None and peer.poll() is None:
                subprocess.run(["sudo", "kill", "-TERM", "--", "-" + str(peer.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    peer.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    subprocess.run(["sudo", "kill", "-KILL", "--", "-" + str(peer.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    peer.wait(timeout=5)
            if instrumentation is not None:
                instrumentation.flush()
                if not result["passed"]:
                    print((report / "instrumentation.txt").read_text()[-12000:], flush=True)
            # Only this disposable emulator is queried. Never include the
            # Linux peer's raw TOML/private log in an uploaded artifact.
            try:
                (report / "logcat.txt").write_text(call("logcat", "-d", "-t", "2000"))
            except (OSError, subprocess.SubprocessError):
                result["logcat_unavailable"] = True
            (report / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            call("shell", "am", "force-stop", PACKAGE)
            call("shell", "rm", "-f", "/data/local/tmp/cmfa-mesh-probe")
            call("shell", "rm", "-f", "/data/local/tmp/cmfa-transition-probe")
            print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
