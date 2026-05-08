"""Quick deploy: base64 encode files, upload via SSH, restart via supervisor."""
import paramiko, os, time, base64

HOST, PORT, USER, PASS = "118.178.140.171", 22, "root", "Zty87968492"
LOCAL = r"C:\Users\zty\Desktop\arteta_bot"
REMOTE = "/opt/arteta_bot"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, PORT, USER, PASS)
print("Connected.")

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    return stdout.read().decode().strip()

def upload_b64(local_path, remote_path):
    """Upload a file via base64 encoding to avoid escaping issues."""
    with open(local_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    cmd = f"echo '{b64}' | base64 -d > {remote_path}"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    err = stderr.read().decode().strip()
    if err:
        print(f"  Upload error for {remote_path}: {err}")
        return False
    return True

# 1. Dirs
run(f"mkdir -p {REMOTE}/plugins")

# 2. Upload files
files = [
    ("bot.py", f"{REMOTE}/bot.py"),
    ("plugins/arteta_image.py", f"{REMOTE}/plugins/arteta_image.py"),
    ("plugins/arteta_chat.py", f"{REMOTE}/plugins/arteta_chat.py"),
]

for local_name, remote_path in files:
    local = os.path.join(LOCAL, local_name)
    ok = upload_b64(local, remote_path)
    print(f"{'OK' if ok else 'FAIL'}: {local_name}")

# 3. Update .env.prod
stdin, stdout, stderr = ssh.exec_command(f"cat {REMOTE}/.env.prod")
current_env = stdout.read().decode()

if "IMAGE_API_KEY" not in current_env:
    additions = """\n# 图片生成（gpt-image-1.5）
IMAGE_API_KEY=sk-5fdiT7sPpX36NkvLykAo5MxKiWftOldkCfMX8kjfrr8VI1kb
IMAGE_API_URL=https://api.duckcoding.ai
IMAGE_MODEL=gpt-image-1.5
"""
    new_env = (current_env.rstrip() + additions).encode()
    b64 = base64.b64encode(new_env).decode()
    run(f"echo '{b64}' | base64 -d > {REMOTE}/.env.prod")
    print("Updated .env.prod")

# 4. Fix ownership
run(f"chown -R arteta:arteta {REMOTE}")
print("Ownership fixed")

# 5. Restart via supervisor
run("supervisorctl restart arteta_bot")
print("Restart issued")
time.sleep(3)

# 6. Verify
print(f"Status: {run('supervisorctl status arteta_bot')}")
print(f"--- Log ---\n{run(f'tail -30 {REMOTE}/bot.log')}")

ssh.close()
print("Done.")
