import json
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ENV_FILE = Path('.env')

def load_env(path):
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values

def prompt(message, default=''):
    answer = input(f"{message}{' [' + default + ']' if default else ''}: ").strip()
    return answer or default

def request_json(url, token, method='GET', data=None, params=None):
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}'
    }
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    payload = None
    if data is not None:
        payload = json.dumps(data).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode('utf-8')
            if raw:
                return json.loads(raw)
            return {}
    except urllib.error.HTTPError as exc:
        message = exc.read().decode('utf-8', errors='ignore')
        try:
            data = json.loads(message)
            msg = data.get('message', message)
        except Exception:
            msg = message or exc.reason
        print(f"GitHub error ({exc.code}): {msg}")
        return None
    except urllib.error.URLError as exc:
        print(f"Network error: {exc}")
        return None

def parse_repo_reference(text):
    text = text.strip()
    if text.startswith('http'):
        parsed = urllib.parse.urlparse(text)
        if parsed.path:
            parts = parsed.path.lstrip('/').rstrip('/').replace('.git', '').split('/')
            if len(parts) >= 2:
                return parts[0], parts[1]
    if '/' in text:
        parts = text.strip().split('/')
        if len(parts) >= 2:
            return parts[0], parts[1]
    return None, None

def repo_info(token, owner, repo):
    return request_json(f"https://api.github.com/repos/{owner}/{repo}", token)

def get_default_repo(values):
    owner = values.get('GITHUB_OWNER')
    repo = values.get('GITHUB_REPO', 'github-downloader')
    if owner:
        return owner, repo
    print('Repository owner not found in .env.')
    while True:
        answer = prompt('Enter GitHub repo URL or owner/repo')
        if not answer:
            continue
        owner, repo = parse_repo_reference(answer)
        if owner and repo:
            return owner, repo

def select_branch(info):
    return info.get('default_branch') or 'main'

def get_latest_run_id(token, owner, repo, branch, workflow):
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/runs"
    runs = request_json(url, token, params={"branch": branch, "event": "workflow_dispatch", "per_page": 5})
    if not runs or 'workflow_runs' not in runs or not runs['workflow_runs']:
        return None
    for run in runs['workflow_runs']:
        if run.get('head_branch') == branch:
            return run.get('id')
    return runs['workflow_runs'][0].get('id')

def run_workflow(token, owner, repo, branch, workflow, inputs):
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    result = request_json(url, token, method='POST', data={"ref": branch, "inputs": inputs})
    if result is None:
        return None
    print('Workflow dispatched successfully.')
    run_id = get_latest_run_id(token, owner, repo, branch, workflow)
    if run_id is None:
        print('Workflow dispatch succeeded, but no run was found yet. Check the repository Actions page for the new run.')
    return run_id

def open_log_window(owner, repo, run_id):
    gh = shutil.which('gh')
    if gh:
        command = f'gh run watch {run_id} --repo {owner}/{repo}'
    else:
        url = f'https://github.com/{owner}/{repo}/actions/runs/{run_id}'
        print('Opening GitHub Actions run page in your browser.')
        webbrowser.open(url)
        return
    if platform.system() == 'Windows':
        subprocess.Popen(['cmd', '/c', 'start', 'powershell', '-NoExit', '-Command', command], shell=False)
    else:
        terminal = shutil.which('x-terminal-emulator') or shutil.which('gnome-terminal') or shutil.which('konsole') or shutil.which('xfce4-terminal')
        if terminal:
            subprocess.Popen([terminal, '--', 'bash', '-lc', command])
        else:
            print('No terminal launcher found. Open the run page instead.')
            webbrowser.open(f'https://github.com/{owner}/{repo}/actions/runs/{run_id}')

def show_downloaded_lists(token, owner, repo, branch):
    data = request_json(f"https://api.github.com/repos/{owner}/{repo}/contents/downloads", token, params={"ref": branch})
    if not data:
        print('No downloads directory found or it is empty.')
        return
    print('\nDownloaded categories:')
    for item in data:
        if item.get('type') == 'dir':
            print(f"- {item.get('name')}")
            nested = request_json(f"https://api.github.com/repos/{owner}/{repo}/contents/{item.get('path')}", token, params={"ref": branch})
            if nested:
                for child in nested:
                    if child.get('type') == 'dir':
                        print(f"  - {child.get('name')}")
    print('')

def choose_folder(token, owner, repo, branch):
    types = ['direct', 'youtube', 'telegram']
    print('\nTypes:')
    for idx, name in enumerate(types, 1):
        print(f"{idx}. {name}")
    choice = prompt('Choose a type', '1')
    try:
        selected = types[int(choice) - 1]
    except Exception:
        print('Invalid selection.')
        return None, None
    path = f"downloads/{selected}"
    folders = request_json(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}", token, params={"ref": branch})
    if not folders:
        print('No folders found for that type.')
        return None, None
    dir_names = [item['name'] for item in folders if item.get('type') == 'dir']
    if not dir_names:
        print('No folders found.')
        return None, None
    print('\nAvailable folders:')
    for idx, value in enumerate(dir_names, 1):
        print(f"{idx}. {value}")
    folder_choice = prompt('Choose a folder', '1')
    try:
        return selected, dir_names[int(folder_choice) - 1]
    except Exception:
        print('Invalid folder selection.')
        return None, None

def download_folder(token, owner, repo, branch):
    selected_type, folder_name = choose_folder(token, owner, repo, branch)
    if not selected_type or not folder_name:
        return
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/downloads/{selected_type}/{folder_name}/files/links.txt"
    try:
        with urllib.request.urlopen(raw_url, timeout=30) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
    except Exception as exc:
        print(f"Could not fetch links file: {exc}")
        return
    links = [line.strip() for line in content.splitlines() if line.strip()]
    if not links:
        print('No links found in the folder.')
        return
    links_path = Path(f'download_links_{selected_type}_{folder_name}.txt')
    links_path.write_text('\n'.join(links), encoding='utf-8')
    print(f'Created {links_path}. Launching download terminal...')
    if platform.system() == 'Windows':
        command = f"Get-Content '{links_path}' | ForEach-Object {{ Invoke-WebRequest -Uri $_ -OutFile (Split-Path $_ -Leaf) }}"
        subprocess.Popen(['cmd', '/c', 'start', 'powershell', '-NoExit', '-Command', command], shell=False)
    else:
        terminal = shutil.which('x-terminal-emulator') or shutil.which('gnome-terminal') or shutil.which('konsole') or shutil.which('xfce4-terminal')
        command = f"cd '{Path.cwd()}' && wget -i '{links_path.name}' && exec bash"
        if terminal:
            subprocess.Popen([terminal, '--', 'bash', '-lc', command])
        else:
            print('No terminal launcher found. Use this command:')
            print(command)

def cancel_run(token, owner, repo):
    data = request_json(f"https://api.github.com/repos/{owner}/{repo}/actions/runs", token, params={"status": "in_progress", "per_page": 10})
    if not data or 'workflow_runs' not in data:
        print('No active workflow runs found.')
        return
    runs = data['workflow_runs']
    if not runs:
        print('No active workflow runs found.')
        return
    print('\nActive runs:')
    for idx, run in enumerate(runs, 1):
        print(f"{idx}. {run.get('name')} id={run.get('id')} event={run.get('event')} branch={run.get('head_branch')}")
    choice = prompt('Choose a run to cancel', '1')
    try:
        selected = runs[int(choice) - 1]
    except Exception:
        print('Invalid selection.')
        return
    run_id = selected.get('id')
    if not run_id:
        print('Run ID missing.')
        return
    cancel_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/cancel"
    request_json(cancel_url, token, method='POST')
    print(f'Cancellation requested for run {run_id}.')

def main():
    if not ENV_FILE.exists():
        print('Missing .env file. Copy .env.example and set values before running.')
        input('Press Enter to exit...')
        sys.exit(1)
    env = load_env(ENV_FILE)
    token = env.get('GITHUB_TOKEN')
    if not token:
        print('GITHUB_TOKEN is missing from .env.')
        input('Press Enter to exit...')
        sys.exit(1)
    owner, repo = get_default_repo(env)
    info = repo_info(token, owner, repo)
    if not info:
        print('Repository not found. Please check .env or enter a different repository.')
        owner, repo = get_default_repo(env)
        info = repo_info(token, owner, repo)
        if not info:
            print('Repository could not be resolved.')
            sys.exit(1)
    branch = select_branch(info)
    actions = [
        ('Direct download', 'download.yaml'),
        ('YouTube download', 'youtube.yaml'),
        ('Telegram download', 'telegram.yaml'),
        ('Browse URL', 'browse.yaml'),
        ('Clean downloads', 'clean.yaml'),
        ('Sort downloads', 'sort.yaml'),
        ('Cancel workflow', None),
        ('List downloaded folders', None),
        ('Download folder by id', None),
        ('Exit', None),
    ]
    while True:
        print('\nSelect an action:')
        for idx, (label, _) in enumerate(actions, 1):
            print(f"{idx}. {label}")
        choice = prompt('Enter number', '1')
        try:
            index = int(choice) - 1
        except ValueError:
            print('Invalid number.')
            continue
        if index < 0 or index >= len(actions):
            print('Invalid selection.')
            continue
        label, workflow = actions[index]
        if label == 'Exit':
            break
        if label == 'List downloaded folders':
            show_downloaded_lists(token, owner, repo, branch)
            continue
        if label == 'Download folder by id':
            download_folder(token, owner, repo, branch)
            continue
        if label == 'Cancel workflow':
            cancel_run(token, owner, repo)
            continue
        inputs = {}
        if workflow == 'download.yaml':
            inputs['urls'] = prompt('Enter URLs separated by space')
            inputs['mode'] = prompt('Mode (normal/zip)', 'normal')
            if inputs['mode'] == 'zip':
                inputs['password'] = prompt('Zip password (leave blank for none)', '')
        elif workflow == 'youtube.yaml':
            inputs['mode'] = prompt('Mode (single/playlist/channel/search)', 'single')
            inputs['url'] = prompt('URL or query')
            inputs['type'] = prompt('Type (video/audio)', 'video')
            inputs['quality'] = prompt('Quality or bitrate', '720')
            inputs['max_videos'] = int(prompt('Max results', '10'))
        elif workflow == 'telegram.yaml':
            inputs['telegram_links'] = prompt('Enter Telegram links separated by space')
        elif workflow == 'browse.yaml':
            inputs['url'] = prompt('Enter URL to visit')
        run_id = run_workflow(token, owner, repo, branch, workflow, inputs)
        if run_id:
            open_log_window(owner, repo, run_id)
    print('Goodbye.')


if __name__ == '__main__':
    main()
