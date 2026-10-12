#!/usr/bin/env python3
"""
Antigravity Sync Engine (Machine-Agnostic)
Synchronizes Antigravity chats, projects, databases, and indexes across different machines.
Works seamlessly on macOS and Linux with zero external dependencies.
"""

import os
import sys
import shutil
import socket
import sqlite3
import platform
import subprocess
import argparse
import time
import re
from pathlib import Path

CURRENT_OS = platform.system()
LOCAL_HOME = str(Path.home())
GEMINI_DIR = Path.home() / ".gemini"
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "sync.conf"


def load_config():
    """Load configuration from sync.conf or environment variables."""
    config = {
        "REMOTE_HOST": os.environ.get("AGY_REMOTE_HOST", ""),
        "REMOTE_USER": os.environ.get("AGY_REMOTE_USER", ""),
        "REMOTE_PORT": os.environ.get("AGY_REMOTE_PORT", "22"),
        "SSH_KEY": os.environ.get("AGY_SSH_KEY", ""),
        "SYNC_TAG_PREFIX": os.environ.get("AGY_SYNC_TAG_PREFIX", "[Remote] "),
        "SYNC_TAG_SUFFIX": os.environ.get("AGY_SYNC_TAG_SUFFIX", ""),
    }

    if CONFIG_PATH.is_file():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key in config:
                        config[key] = val

    return config


def prompt_for_missing_config(config):
    """Interactively prompt user for host/user if not specified in config."""
    if not config["REMOTE_HOST"]:
        print("💡 Connection configuration not fully specified in sync.conf.")
        config["REMOTE_HOST"] = input("👉 Enter remote host IP or domain: ").strip()
    if not config["REMOTE_USER"]:
        config["REMOTE_USER"] = input("👉 Enter remote username: ").strip()
    if not config["REMOTE_PORT"]:
        config["REMOTE_PORT"] = "22"
    return config


# ==============================================================================
# Pre-flight Health Check System
# ==============================================================================

def check_local_prerequisites():
    """Check local system dependencies (Python, SSH, Rsync) and report status."""
    print("\n🔍 Checking Local System Prerequisites...")
    all_passed = True

    # 1. Python check
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"  [✓] Python: {py_version} (OK)")

    # 2. Local SSH Client check
    ssh_path = shutil.which("ssh")
    if ssh_path:
        print(f"  [✓] Local SSH Client: {ssh_path} (OK)")
    else:
        print("  [✗] Local SSH Client: MISSING")
        if CURRENT_OS == "Darwin":
            print("      Fix: Install Xcode Command Line Tools via 'xcode-select --install'")
        else:
            print("      Fix: Run 'sudo apt install openssh-client' or equivalent")
        all_passed = False

    # 3. Local Rsync check
    rsync_path = shutil.which("rsync")
    if rsync_path:
        print(f"  [✓] Local Rsync: {rsync_path} (OK)")
    else:
        print("  [✗] Local Rsync: MISSING")
        if CURRENT_OS == "Darwin":
            print("      Fix: Run 'brew install rsync'")
        else:
            print("      Fix: Run 'sudo apt install rsync'")
        all_passed = False

    if not all_passed:
        print("\n❌ Local prerequisites check failed. Please install the missing tools and try again.")
        sys.exit(1)

    print("  ✨ All local prerequisites satisfied.\n")


def check_remote_prerequisites(config):
    """
    Check if the remote host is reachable, SSH port is open,
    authentication succeeds, and remote rsync is installed.
    """
    host = config["REMOTE_HOST"]
    port = int(config.get("REMOTE_PORT", 22))
    user = config["REMOTE_USER"]

    print(f"🔍 Checking Remote System Prerequisites ({user}@{host}:{port})...")

    # 1. Network / Port reachability check
    try:
        with socket.create_connection((host, port), timeout=5):
            print(f"  [✓] Network Reachability: {host}:{port} is open and accepting connections.")
    except socket.timeout:
        print(f"  [✗] Connection Timed Out: Could not reach {host}:{port} within 5 seconds.")
        print("      Possible causes:")
        print("      - Target machine is offline or asleep.")
        print("      - Target IP address is incorrect.")
        print("      - Firewall / VPN is blocking port 22.")
        sys.exit(1)
    except (socket.error, OSError) as e:
        print(f"  [✗] Connection Refused: Could not reach {host}:{port} ({e}).")
        print("      Possible causes:")
        print("      - SSH server is not running on the remote machine.")
        print("        Fix on Linux: 'sudo systemctl start ssh'")
        print("        Fix on macOS: System Settings -> General -> Sharing -> Enable Remote Login.")
        sys.exit(1)

    # 2. SSH Authentication and Remote Tool Verification
    ssh_opts = f"-p {port} -o BatchMode=no -o ConnectTimeout=10"
    if config["SSH_KEY"]:
        ssh_opts += f" -i {config['SSH_KEY']}"

    remote_probe_cmd = (
        f"ssh {ssh_opts} {user}@{host} "
        f"'echo \"__REMOTE_CHECK__\" && which rsync && echo $HOME'"
    )

    try:
        res = subprocess.run(remote_probe_cmd, shell=True, capture_output=True, text=True, check=True)
        lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]

        if "__REMOTE_CHECK__" in lines:
            print(f"  [✓] SSH Authentication: Success (Logged in as {user}).")
            
            rsync_index = lines.index("__REMOTE_CHECK__") + 1
            if rsync_index < len(lines) and "rsync" in lines[rsync_index]:
                print(f"  [✓] Remote Rsync: Installed ({lines[rsync_index]}).")
                remote_home = lines[rsync_index + 1] if (rsync_index + 1) < len(lines) else f"/home/{user}"
                print(f"  [✓] Remote Home Directory: {remote_home}")
                print("  ✨ All remote prerequisites satisfied.\n")
                return remote_home
            else:
                print("  [✗] Remote Rsync: NOT FOUND on the target machine.")
                print("      Fix on remote Linux: 'sudo apt install rsync'")
                print("      Fix on remote macOS: 'brew install rsync'")
                sys.exit(1)

    except subprocess.CalledProcessError as e:
        err = e.stderr.strip()
        print(f"  [✗] SSH Authentication Failed: {err}")
        print("      Possible causes:")
        print("      - Incorrect remote password or invalid SSH key.")
        print("      - Permission denied for user on remote machine.")
        print(f"      - Tip: Try running manually: ssh -p {port} {user}@{host}")
        sys.exit(1)

    return f"/home/{user}"


# ==============================================================================
# Process Lifecycle Management
# ==============================================================================

def run_cmd(cmd, check=True):
    """Run shell command with streaming output."""
    res = subprocess.run(cmd, shell=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {res.returncode}: {cmd}")
    return res


def is_antigravity_running():
    """Check if Antigravity or its language server is running on the current machine."""
    if CURRENT_OS == "Darwin":
        res = subprocess.run(["pgrep", "-f", "/Applications/Antigravity.app"], capture_output=True)
        return res.returncode == 0
    elif CURRENT_OS == "Linux":
        res = subprocess.run(["pgrep", "-f", "antigravity"], capture_output=True)
        return res.returncode == 0
    return False


def quit_antigravity():
    """Gracefully close Antigravity and wait for complete shutdown."""
    if not is_antigravity_running():
        return

    print("🔄 Antigravity is currently running. Closing gracefully to flush state...")
    if CURRENT_OS == "Darwin":
        subprocess.run([
            "osascript", "-e",
            'tell application id "com.google.antigravity" to quit'
        ], capture_output=True)
        subprocess.run(["osascript", "-e", 'quit app "Antigravity"'], capture_output=True)

        timeout = 20
        start = time.time()
        while is_antigravity_running() and (time.time() - start < timeout):
            time.sleep(0.5)

    elif CURRENT_OS == "Linux":
        subprocess.run(["pkill", "-TERM", "-f", "antigravity"], capture_output=True)
        timeout = 15
        start = time.time()
        while is_antigravity_running() and (time.time() - start < timeout):
            time.sleep(0.5)

    time.sleep(2.0)
    print("✅ Antigravity and backend language server closed cleanly.")


def launch_antigravity():
    """Relaunch Antigravity after sync."""
    print("🚀 Relaunching Antigravity...")
    if CURRENT_OS == "Darwin":
        subprocess.run(["open", "-a", "Antigravity"])
    elif CURRENT_OS == "Linux":
        if subprocess.run(["which", "antigravity"], capture_output=True).returncode == 0:
            subprocess.Popen(["antigravity"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif subprocess.run(["which", "gtk-launch"], capture_output=True).returncode == 0:
            subprocess.run(["gtk-launch", "antigravity"], capture_output=True)
        else:
            print("ℹ️  Please open Antigravity manually from your application menu.")


# ==============================================================================
# Sync & Path Remapping Engine
# ==============================================================================

def parse_varint(data, pos):
    val, shift = 0, 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        val |= (b & 0x7f) << shift
        if not (b & 0x80):
            break
        shift += 7
    return val, pos


def encode_varint(val):
    out = bytearray()
    while val > 0x7f:
        out.append((val & 0x7f) | 0x80)
        val >>= 7
    out.append(val & 0x7f)
    return bytes(out)


def parse_fields(data):
    fields = []
    pos = 0
    while pos < len(data):
        tag, pos = parse_varint(data, pos)
        field_num = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:
            val, pos = parse_varint(data, pos)
            fields.append((field_num, wire_type, val))
        elif wire_type in (1, 5):
            n = 8 if wire_type == 1 else 4
            fields.append((field_num, wire_type, data[pos:pos+n]))
            pos += n
        elif wire_type == 2:
            length, pos = parse_varint(data, pos)
            fields.append((field_num, wire_type, data[pos:pos+length]))
            pos += length
        else:
            raise ValueError(f"Unsupported wire type {wire_type}")
    return fields


def serialize_fields(fields):
    out = bytearray()
    for field_num, wire_type, val in fields:
        tag = (field_num << 3) | wire_type
        out.extend(encode_varint(tag))
        if wire_type == 0:
            out.extend(encode_varint(val))
        elif wire_type in (1, 5):
            out.extend(val)
        elif wire_type == 2:
            if isinstance(val, list):
                payload = serialize_fields(val)
            else:
                payload = val
            out.extend(encode_varint(len(payload)))
            out.extend(payload)
    return bytes(out)


def sync_files(config, remote_home):
    """Sync core components using rsync, pulling summaries to staging."""
    print("📥 Syncing Antigravity components...")

    ssh_opts = f"-p {config['REMOTE_PORT']}"
    if config["SSH_KEY"]:
        ssh_opts += f" -i {config['SSH_KEY']}"
    rsh_flag = f"-e 'ssh {ssh_opts}'"

    user_host = f"{config['REMOTE_USER']}@{config['REMOTE_HOST']}"
    staging_proto = "/tmp/remote_staging_proto.pb"

    targets = [
        # 1. Brain: Transcripts & Artifacts
        (f"{user_host}:{remote_home}/.gemini/antigravity/brain/", f"{LOCAL_HOME}/.gemini/antigravity/brain/"),
        # 2. Conversations: History SQLite Databases
        (f"{user_host}:{remote_home}/.gemini/antigravity/conversations/", f"{LOCAL_HOME}/.gemini/antigravity/conversations/"),
        # 3. Projects Config
        (f"{user_host}:{remote_home}/.gemini/config/projects/", f"{LOCAL_HOME}/.gemini/config/projects/"),
        # 4. Titles Index Protobuf (pulled to STAGING to avoid clobbering local chats)
        (f"{user_host}:{remote_home}/.gemini/antigravity/agyhub_summaries_proto.pb", staging_proto),
        # 5. Annotations: Custom Titles & User Metadata
        (f"{user_host}:{remote_home}/.gemini/antigravity/annotations/", f"{LOCAL_HOME}/.gemini/antigravity/annotations/"),
    ]

    for src, dst in targets:
        dst_path = Path(dst)
        if dst.endswith("/"):
            dst_path.mkdir(parents=True, exist_ok=True)
        else:
            dst_path.parent.mkdir(parents=True, exist_ok=True)

        target_name = Path(src).name or Path(src).parent.name
        print(f"\n📦 Syncing [{target_name}]...")
        cmd = f"rsync -avzP {rsh_flag} {src} {dst}"
        run_cmd(cmd, check=False)


def fix_paths(remote_home, local_home):
    """
    Intelligently replace remote absolute paths with local absolute paths
    in transcript files, project configuration files, and conversation database blobs.
    """
    print("\n🔧 Automatically remapping paths to local system...")

    # 1. Fix brain transcripts
    brain_dir = GEMINI_DIR / "antigravity" / "brain"
    count_transcripts = 0
    if brain_dir.is_dir():
        for p in brain_dir.glob("*/.system_generated/logs/transcript*.jsonl"):
            try:
                content = p.read_text(encoding="utf-8")
                if remote_home in content:
                    new_content = content.replace(remote_home, local_home)
                    p.write_text(new_content, encoding="utf-8")
                    count_transcripts += 1
            except Exception as e:
                print(f"Warning: could not process {p}: {e}")

    # 2. Fix project configuration files
    projects_dir = GEMINI_DIR / "config" / "projects"
    count_projects = 0
    if projects_dir.is_dir():
        for p in projects_dir.glob("*.json"):
            try:
                content = p.read_text(encoding="utf-8")
                if remote_home in content:
                    new_content = content.replace(remote_home, local_home)
                    p.write_text(new_content, encoding="utf-8")
                    count_projects += 1
            except Exception as e:
                print(f"Warning: could not process {p}: {e}")

    # 3. Fix trajectory_metadata_blob in conversation databases
    conv_dir = GEMINI_DIR / "antigravity" / "conversations"
    count_blobs = 0
    if conv_dir.is_dir():
        r_bytes = remote_home.encode("utf-8")
        l_bytes = local_home.encode("utf-8")
        for db in conv_dir.glob("*.db"):
            try:
                conn = sqlite3.connect(db)
                cur = conn.cursor()
                cur.execute('SELECT data FROM trajectory_metadata_blob WHERE id="main"')
                row = cur.fetchone()
                if row and r_bytes in row[0]:
                    blob = row[0]
                    fields = parse_fields(blob)
                    new_fields = []
                    for fn, wt, val in fields:
                        if wt == 2 and r_bytes in val:
                            try:
                                sub = parse_fields(val)
                                new_sub = []
                                for sfn, swt, sval in sub:
                                    if swt == 2 and r_bytes in sval:
                                        new_sub.append((sfn, swt, sval.replace(r_bytes, l_bytes)))
                                    else:
                                        new_sub.append((sfn, swt, sval))
                                new_fields.append((fn, wt, serialize_fields(new_sub)))
                            except Exception:
                                new_fields.append((fn, wt, val.replace(r_bytes, l_bytes)))
                        else:
                            new_fields.append((fn, wt, val))
                    cur.execute('UPDATE trajectory_metadata_blob SET data = ? WHERE id="main"', (serialize_fields(new_fields),))
                    conn.commit()
                    count_blobs += 1
                conn.close()
            except Exception as e:
                print(f"Warning: could not process {db}: {e}")

    print(f"✅ Path remapping complete: {count_transcripts} transcripts, {count_projects} projects, and {count_blobs} conversation databases updated.")


def merge_and_lock_conversations(config, remote_home, local_home):
    """
    Reads incoming conversations from staging proto, merges them into the local
    Protobuf sidebar index without losing native chats, and locks them into
    conversation_summaries.db so titles never revert upon clicking.
    """
    prefix = config.get("SYNC_TAG_PREFIX", "")
    suffix = config.get("SYNC_TAG_SUFFIX", "")

    staging_path = Path("/tmp/remote_staging_proto.pb")
    local_proto_path = GEMINI_DIR / "antigravity" / "agyhub_summaries_proto.pb"

    if not staging_path.is_file():
        print("ℹ️  No remote staging proto found to merge.")
        return

    print("\n🏷️  Dynamically merging and locking incoming conversations...")

    remote_entries = {}
    try:
        raw_staging = staging_path.read_bytes()
        r_root = parse_fields(raw_staging)
        for fn, wt, val in r_root:
            sub = parse_fields(val)
            u_str = ""
            t_str = ""
            for sfn, swt, sval in sub:
                if sfn == 1 and swt == 2:
                    u_str = sval.decode("utf-8", errors="ignore")
                elif sfn == 2 and swt == 2:
                    inner = parse_fields(sval)
                    for ifn, iwt, ival in inner:
                        if ifn == 1 and iwt == 2:
                            if not t_str:
                                t_str = ival.decode("utf-8", errors="ignore")
                        elif ifn == 15 and iwt == 2:
                            try:
                                f15 = parse_fields(ival)
                                for pfn, pwt, pval in f15:
                                    if pfn == 1 and pwt == 2:
                                        t15 = pval.decode("utf-8", errors="ignore").rstrip(":")
                                        if t15:
                                            t_str = t15
                            except Exception:
                                pass
            if u_str and t_str:
                if prefix and not t_str.startswith(prefix):
                    t_str = f"{prefix}{t_str}"
                if suffix and not t_str.endswith(suffix):
                    t_str = f"{t_str}{suffix}"
                remote_entries[u_str] = (t_str, val)
        print(f"Parsed {len(remote_entries)} incoming remote conversations.")
    except Exception as e:
        print(f"Warning on parsing staging proto: {e}")

    # Merge into local Protobuf index
    if local_proto_path.is_file() and remote_entries:
        try:
            local_raw = local_proto_path.read_bytes()
            l_root = parse_fields(local_raw)
            merged_root = []
            seen_uuids = set()

            for fn, wt, val in l_root:
                if wt != 2:
                    merged_root.append((fn, wt, val))
                    continue
                sub = parse_fields(val)
                u_str = ""
                for sfn, swt, sval in sub:
                    if sfn == 1 and swt == 2:
                        u_str = sval.decode("utf-8", errors="ignore")
                        break
                if u_str in remote_entries:
                    seen_uuids.add(u_str)
                    new_title = remote_entries[u_str][0]
                    new_sub = []
                    for sfn, swt, sval in sub:
                        if sfn == 2 and swt == 2:
                            inner = parse_fields(sval)
                            new_inner = []
                            for ifn, iwt, ival in inner:
                                if ifn == 1 and iwt == 2:
                                    new_inner.append((ifn, iwt, new_title.encode("utf-8")))
                                elif ifn == 15 and iwt == 2:
                                    try:
                                        f15 = parse_fields(ival)
                                        new_f15 = []
                                        for pfn, pwt, pval in f15:
                                            if pfn == 1 and pwt == 2:
                                                new_f15.append((pfn, pwt, (new_title + ":").encode("utf-8")))
                                            else:
                                                new_f15.append((pfn, pwt, pval))
                                        new_inner.append((ifn, iwt, serialize_fields(new_f15)))
                                    except Exception:
                                        new_inner.append((ifn, iwt, ival))
                                else:
                                    new_inner.append((ifn, iwt, ival))
                            new_sub.append((sfn, swt, serialize_fields(new_inner)))
                        else:
                            new_sub.append((sfn, swt, sval))
                    merged_root.append((fn, wt, serialize_fields(new_sub)))
                else:
                    merged_root.append((fn, wt, val))

            for r_uid, (r_t, r_val) in remote_entries.items():
                if r_uid not in seen_uuids:
                    merged_root.append((1, 2, r_val))

            local_proto_path.write_bytes(serialize_fields(merged_root))
            print(f"✅ Merged local Protobuf index: {len(merged_root)} total conversations.")

        except Exception as e:
            print(f"Warning on updating local proto: {e}")

    # Synchronize into ~/.gemini/antigravity/annotations/*.pbtxt
    annot_dir = GEMINI_DIR / "antigravity" / "annotations"
    annot_dir.mkdir(parents=True, exist_ok=True)
    count_annot = 0
    for uid, (title, _) in remote_entries.items():
        pbtxt_file = annot_dir / f"{uid}.pbtxt"
        content = ""
        if pbtxt_file.is_file():
            try:
                content = pbtxt_file.read_text(encoding="utf-8")
            except Exception:
                pass
        match = re.search(r'title\s*:\s*"([^"]*)"', content)
        if match:
            cur_t = match.group(1)
            if prefix and not cur_t.startswith(prefix):
                new_t = f"{prefix}{cur_t}"
                content = content[:match.start(1)] + new_t + content[match.end(1):]
        else:
            content = f'title:"{title}" ' + content.strip()
        try:
            pbtxt_file.write_text(content.strip() + "\n", encoding="utf-8")
            count_annot += 1
        except Exception as e:
            print(f"Warning writing annotation for {uid}: {e}")
    if count_annot > 0:
        print(f"✅ Locked {count_annot} custom titles into annotation files.")

    # Synchronize into conversation_summaries.db and patch paths
    db_path = GEMINI_DIR / "antigravity" / "conversation_summaries.db"
    if db_path.is_file() and remote_entries:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            updated_db = 0
            for uid, (title, _) in remote_entries.items():
                cur.execute("""
                    UPDATE conversation_summaries
                    SET title = ?, workspace_uris = replace(workspace_uris, ?, ?)
                    WHERE conversation_id = ?
                """, (title, remote_home, local_home, uid))
                if cur.rowcount > 0:
                    updated_db += 1
                else:
                    cur.execute("""
                        INSERT OR IGNORE INTO conversation_summaries 
                        (conversation_id, title, preview, step_count, last_modified_time, workspace_uris, last_user_input_time, app_data_dir)
                        VALUES (?, ?, ?, 1, datetime('now'), ?, datetime('now'), 'antigravity')
                    """, (uid, title, title, f'["file://{local_home}/Downloads/interface_test_v02_files"]'))
                    updated_db += 1

            cur.execute("""
                UPDATE conversation_summaries
                SET workspace_uris = replace(workspace_uris, ?, ?)
            """, (remote_home, local_home))
            conn.commit()
            conn.close()
            print(f"✅ Locked {updated_db} titles into SQLite database.")

        except Exception as e:
            print(f"Warning on updating SQLite DB: {e}")

    if staging_path.is_file():
        staging_path.unlink()


# ==============================================================================
# Main Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Antigravity Cross-Platform Sync Engine")
    parser.add_argument("action", choices=["pull"], default="pull", nargs="?", help="Sync direction (pull from remote)")
    parser.add_argument("--no-relaunch", action="store_true", help="Do not relaunch Antigravity after sync")
    args = parser.parse_args()

    print("==================================================")
    print("      Antigravity Universal Sync Engine          ")
    print(f"      Host OS: {CURRENT_OS}                      ")
    print("==================================================")

    config = load_config()
    config = prompt_for_missing_config(config)

    # 1. Pre-flight Checks
    check_local_prerequisites()
    remote_home = check_remote_prerequisites(config)

    # 2. Graceful shutdown
    quit_antigravity()

    # 3. Rsync data (using staging for summaries)
    sync_files(config, remote_home)

    # 4. Automatically fix all paths in transcripts, projects, and conversation DBs
    fix_paths(remote_home, LOCAL_HOME)

    # 5. Dynamically merge and permanently lock titles into both Protobuf and SQLite stores
    merge_and_lock_conversations(config, remote_home, LOCAL_HOME)

    # 6. Relaunch
    if not args.no_relaunch:
        launch_antigravity()

    print("\n🎉 All operations completed successfully! Your Antigravity chats are ready.")


if __name__ == "__main__":
    main()
