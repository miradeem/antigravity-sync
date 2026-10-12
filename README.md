# Antigravity Sync (Cross-Platform)

A machine-agnostic synchronization utility for **Google Antigravity (AGY)** conversations, workspaces, and history databases.

## Why This Exists
Antigravity stores its conversations locally in `~/.gemini/antigravity/` using a combination of:
1. `brain/` (Markdown artifacts, transcripts, and step execution logs).
2. `conversations/` (SQLite database tracking files for the History UI and trajectory metadata).
3. `config/projects/` (Workspace and project metadata).
4. `agyhub_summaries_proto.pb` (Central index for conversation titles and project bindings).
5. `annotations/` (Master custom titles and user metadata in `.pbtxt` format).

Because Antigravity relies on exact local absolute paths (e.g. `/home/username/...` on Linux vs `/Users/username/...` on macOS), copying files directly across machines causes the backend to fail or drop conversations.

This tool:
* **Pre-flight Health Checks**: Verifies local and remote Python, SSH, network reachability, and Rsync before attempting transfer.
* **Graceful Shutdown**: Automatically closes Antigravity and its language server before syncing to prevent cache corruption.
* **Dynamic Remote Discovery**: Queries the remote machine over SSH to discover remote home paths (`$HOME`) on the fly.
* **Component Sync**: Syncs all critical data components via `rsync` (Brain transcripts, conversation databases, project workspaces, conversation summaries, and chat annotations).
* **Automatic Path Remapping**: Dynamically scans and rewrites all absolute remote paths to match local paths across JSON configs, SQLite database trajectory blobs, and transcripts.
* **Triple-Layer Title Synchronization**: Synchronizes and locks custom titles across Chat Annotations (`annotations/*.pbtxt`), the Protobuf sidebar index (`agyhub_summaries_proto.pb`), and the SQLite backend database (`conversation_summaries.db`), ensuring titles never revert to raw prompt text when clicked.
* **Automatic Chat Tagging**: Prepends or appends a customizable tag (e.g. `[Remote] `, `[Linux] `) to imported chat titles so they are immediately distinguishable.
* **Auto Relaunch**: Reopens Antigravity once synchronization is complete.

---

## Directory Structure
* `agy_sync.py`: Universal Python sync engine (works on macOS and Linux with zero external dependencies).
* `sync.sh`: Bash wrapper script for command-line convenience.
* `sync.conf.example`: Example connection configuration file.
* `sync.conf`: Your active connection configuration (git-ignored).
* `original_scripts/`: Exact copies of your original baseline shell scripts for reference.

---

## Setup & Usage

### 1. Configure Connection
Copy `sync.conf.example` to `sync.conf` and update your remote machine details:
```bash
cp sync.conf.example sync.conf
```
Edit `sync.conf` with your remote IP, remote user, and optional SSH port/key.

### 2. Run the Sync
```bash
# Pull from remote machine to local machine (default)
./sync.sh pull

# Or run directly via Python
python3 agy_sync.py pull
```
