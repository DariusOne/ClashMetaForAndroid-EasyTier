#!/usr/bin/env python3
"""Build the pinned native engine, without downloading a toolchain implicitly."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NDK = "29.0.14206865"
TARGETS = {
    "arm64-v8a": ("aarch64-linux-android", "aarch64-linux-android21"),
    "x86_64": ("x86_64-linux-android", "x86_64-linux-android21"),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--abi", choices=TARGETS, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "core/build/native-jni")
    args = parser.parse_args()
    expected = "8428a89d2dabc94c97d370ec607c6ca142473626"
    sha = subprocess.check_output(["git", "-C", str(ROOT / "native/easytier-upstream"), "rev-parse", "HEAD"], text=True).strip()
    if sha != expected:
        raise RuntimeError("Unexpected EasyTier revision")
    sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if not sdk:
        raise RuntimeError("Set ANDROID_SDK_ROOT to an installed Android SDK")
    host = "windows-x86_64" if sys.platform == "win32" else "linux-x86_64"
    toolchain = Path(sdk) / "ndk" / NDK / "toolchains/llvm/prebuilt" / host / "bin"
    target, compiler = TARGETS[args.abi]
    suffix = ".cmd" if sys.platform == "win32" else ""
    clang = toolchain / (compiler + "-clang" + suffix)
    if not clang.is_file():
        raise RuntimeError("Install the pinned NDK before building")
    env = os.environ.copy()
    env["CARGO_TARGET_" + target.upper().replace("-", "_") + "_LINKER"] = str(clang)
    env["CC_" + target.replace("-", "_")] = str(clang)
    env["AR_" + target.replace("-", "_")] = str(toolchain / ("llvm-ar.exe" if sys.platform == "win32" else "llvm-ar"))
    env["CARGO_TARGET_DIR"] = str(ROOT / "build/rust")
    env["CARGO_BUILD_JOBS"] = env.get("CARGO_BUILD_JOBS", "2")
    manifest = ROOT / "native/easytier-bridge/Cargo.toml"
    subprocess.run(["cargo", "+1.95.0", "build", "--locked", "--release", "--target", target, "--manifest-path", str(manifest)], env=env, check=True)
    source = Path(env["CARGO_TARGET_DIR"]) / target / "release/libcmfa_easytier.so"
    destination = args.output.resolve() / args.abi
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination / source.name)
    metadata = {"easytier_commit":sha, "rust":"1.95.0", "ndk":NDK, "abi":args.abi, "sha256":hashlib.sha256(source.read_bytes()).hexdigest(), "device_validated":False}
    (destination / "build-info.json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(metadata))


if __name__ == "__main__":
    main()
