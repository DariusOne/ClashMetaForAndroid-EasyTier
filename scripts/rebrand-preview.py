#!/usr/bin/env python3
"""Merge branding resources into a tested APK without rebuilding executable code.

Inputs are local APKs; the second must have been built with Apktool --no-src,
--copy-original and --no-crunch. Output is unsigned and must be aligned/signed.
All non-branding resource IDs/values and every executable/asset/manifest byte
are checked. Resource compiler path changes do not replace original XML bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile


BRANDING = {"string/application_name", "string/launch_name",
            "drawable/ic_launcher_foreground", "mipmap/ic_launcher",
            "mipmap/ic_launcher_round"}
LOGO = "drawable/clash_easytier_logo"
FILE = re.compile(r"\(file\) (res/\S+) type=(\S+)")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def signature(path):
    return path.upper() == "META-INF/MANIFEST.MF" or bool(
        re.fullmatch(r"META-INF/[^/]+\.(?:SF|RSA|DSA|EC)", path, re.I))


def resources(aapt2, apk):
    text = subprocess.check_output([str(aapt2), "dump", "resources", str(apk)],
                                   encoding="utf-8", errors="strict")
    result = {}
    key = None
    for line in text.splitlines():
        match = re.match(r"\s*resource (0x[0-9a-f]+) (\S+)", line)
        if match:
            key = match.group(2)
            if key in result:
                raise ValueError("DUPLICATE_RESOURCE")
            result[key] = {"id": match.group(1), "values": []}
        elif re.match(r"^  type ", line):
            key = None
        elif key and line.strip():
            result[key]["values"].append(line.strip())
    return result


def normalized(name, values):
    values = [FILE.sub("(file) <PATH> type=\\2", line) for line in values]
    # Enum/flag map order is not significant; array/style order is preserved.
    if name.startswith("attr/") and values:
        values = values[:1] + sorted(values[1:])
    return values


def merge(original, rebuilt, logo, output, aapt2):
    before, after = resources(aapt2, original), resources(aapt2, rebuilt)
    if set(before) - set(after) or set(after) - set(before) != {LOGO}:
        raise ValueError("UNEXPECTED_RESOURCE_SET_CHANGE")
    old_files = {}
    branding_files = set()
    for name, entry in before.items():
        current = after[name]
        if current["id"] != entry["id"]:
            raise ValueError("RESOURCE_ID_CHANGED")
        if name in BRANDING:
            branding_files.update(m.group(1) for line in current["values"]
                                  if (m := FILE.search(line)))
            continue
        if normalized(name, entry["values"]) != normalized(name, current["values"]):
            raise ValueError("NON_BRANDING_RESOURCE_CHANGED: " + name)
        for old, new in zip(entry["values"], current["values"]):
            x, y = FILE.search(old), FILE.search(new)
            if x and y:
                if y.group(1) in old_files and old_files[y.group(1)] != x.group(1):
                    raise ValueError("AMBIGUOUS_RESOURCE_FILE")
                old_files[y.group(1)] = x.group(1)
    for name in ("string/application_name", "string/launch_name"):
        if after[name]["values"] != ['() "Clash Easytier"']:
            raise ValueError("APP_LABEL_MISMATCH")
    logo_paths = {m.group(1) for line in after[LOGO]["values"]
                  if (m := FILE.search(line))}
    if len(logo_paths) != 1:
        raise ValueError("LOGO_RESOURCE_MISMATCH")
    branding_files |= logo_paths
    logo_bytes = logo.read_bytes()
    protected = {}
    with zipfile.ZipFile(original) as old, zipfile.ZipFile(rebuilt) as new:
        if len(old.namelist()) != len(set(old.namelist())) or len(new.namelist()) != len(set(new.namelist())):
            raise ValueError("DUPLICATE_ZIP_ENTRY")
        if any(new.read(path) != logo_bytes for path in logo_paths):
            raise ValueError("LOGO_BYTES_CHANGED")
        with zipfile.ZipFile(output, "w") as dest:
            for info in old.infolist():
                if info.filename.startswith("res/") or info.filename == "resources.arsc" or signature(info.filename):
                    continue
                data = old.read(info)
                dest.writestr(info, data)
                protected[info.filename] = sha(data)
            dest.writestr(new.getinfo("resources.arsc"), new.read("resources.arsc"))
            for path, old_path in old_files.items():
                dest.writestr(new.getinfo(path), old.read(old_path))
            for path in sorted(branding_files):
                data = new.read(path)
                # Keep even legacy density fallbacks on the supplied artwork.
                if path.endswith(".png"):
                    data = logo_bytes
                dest.writestr(new.getinfo(path), data)
        with zipfile.ZipFile(output) as dest:
            for path, digest in protected.items():
                if sha(dest.read(path)) != digest:
                    raise ValueError("PROTECTED_APK_ENTRY_CHANGED")
            for path, old_path in old_files.items():
                if dest.read(path) != old.read(old_path):
                    raise ValueError("NON_BRANDING_FILE_CHANGED")
            if dest.testzip() is not None:
                raise ValueError("APK_ZIP_CORRUPT")
    return {
        "schema": 1, "application_name": "Clash Easytier",
        "baseline_apk_sha256": sha(original.read_bytes()),
        "logo_sha256": sha(logo_bytes), "protected_entries": protected,
        "preserved_dex_count": sum(bool(re.fullmatch(r"classes\d*\.dex", p)) for p in protected),
        "preserved_native_library_count": sum(p.startswith("lib/") and p.endswith(".so") for p in protected),
        "preserved_non_branding_resource_files": len(old_files),
        "existing_resource_ids_unchanged": True,
        "non_branding_resource_values_unchanged": True,
        "runtime_network_retested": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original", "rebuilt", "logo", "output", "aapt2", "report"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.report.exists():
        parser.error("Output/report already exists; refusing to replace it")
    report = merge(args.original, args.rebuilt, args.logo, args.output, args.aapt2)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("BRANDING_MERGE_OK: executable code, manifest and assets preserved")


if __name__ == "__main__":
    main()
