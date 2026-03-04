# This script is used to filter the commit based on the commit information, check function commit_filter
# The url of commits that pass the cleaning are stored in {ROOT_PATH}/commit_info/{lang}_filtered_commit_urls.json
import re
import os
import json
import subprocess
import threading

from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
    
def remove_pull_id(commit_message):
    # 定义匹配 pull request ID 的正则表达式
    pull_id_pattern = re.compile(r'\(#(\d+)\)')

    # 替换匹配到的 pull request ID 及其括号
    updated_message = re.sub(pull_id_pattern, '', commit_message).strip()

    return updated_message

def get_commit_message(repo_path, commit_id):
   try:
       result = subprocess.run(
           ['git', '-C', repo_path, 'log', '--format=%B', '-n', '1', commit_id],
           capture_output=True,
           text=True,
           check=True
       )
       return result.stdout.strip()
   except subprocess.CalledProcessError as e:
       print(f"Error getting commit message for {commit_id}: {e}")
       return ""
   except Exception as e:
       print(f"Unexpected error: {e}")
       return ""

def is_bot_commit(repo_path, commit_id):
    try:
        result = subprocess.run(
            ['git', '-C', repo_path, 'log', '--format=%an|%ae|%cn|%ce', '-n', '1', commit_id],
            capture_output=True,
            text=True,
            check=True
        )
        
        author_name, author_email, committer_name, committer_email = result.stdout.strip().split('|')
        
        fields_to_check = [author_name, author_email, committer_name, committer_email]
        
        bot_keywords = ['bot', 'automated', 'github-actions', 'dependabot', 'renovate', 
                        'auto', 'ci', 'deploy', 'merge-bot', 'release-bot']
        
        for field in fields_to_check:
            if field: 
                field_lower = field.lower()
                for keyword in bot_keywords:
                    if keyword in field_lower:
                        return True
        
        return False
        
    except subprocess.CalledProcessError as e:
        print(f"Error getting commit info for {commit_id}: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False
   
def commit_filter(commit):
    from a0 import REPOS_PATH
    def detect_multiple_edit_intent(msg):
        # should at least have imperative mood
        imperative_regex = re.compile(r'\b(?:fix|add|change|update|remove|refactor|improve|make|start|stop|debug|test|ensure|delete|merge|move|rename|clean|correct|allow|avoid|implement|complete|revert|set|increase|decrease|optimize|docs)\b', re.IGNORECASE)
        matches = imperative_regex.findall(msg)
        if len(matches) == 0:
            return False
        title = msg.split("\n")[0]
        body = "\n".join(msg.split("\n")[1:])

        # when body is empty
        if body.strip() == "":
            target = title
        else:
            target = body

        matches = imperative_regex.findall(msg)
        if len(set(matches)) == 1:
            return True
        else:
            return False
    
    commit_id = commit.split("/")[-1]
    project_name = commit.split("/")[-3]
    repo_path = os.path.join(REPOS_PATH, project_name)

    commit_msg = get_commit_message(repo_path, commit_id)  
    # 1. return False if commit message contain multiple edit intents
    single_intent = detect_multiple_edit_intent(commit_msg)
    if not single_intent:
        raise ValueError('1 Commit msg contain > 1 edit intention')
    
    # 2. return False if commit message is not in English
    if not commit_msg.isascii():
        raise ValueError('2 Commit msg contain non-ascii char')
    
    # 3. return False if commit merge pull request, merge branch
    if "Merge pull request" in commit_msg or "Merge branch" in commit_msg:
        raise ValueError('3 Merge pull request / branch commit')
    
    # 4. return False if commit is bot commit
    if is_bot_commit(repo_path, commit_id):
        raise ValueError('4 Bot commit')
    
    return True

def get_all_commit_ids(repo_path):
    try:
        result = subprocess.run(
            ['git', '-C', repo_path, 'rev-list', '--all'],
            capture_output=True,
            text=True,
            check=True
        )
        commit_ids = [line.strip() for line in result.stdout.split('\n') if line.strip()]
        return commit_ids
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
        return []
   
def clean_commit(lang):
    from a0 import ROOT_PATH
    from a0 import REPOS_PATH
    with open(os.path.join(ROOT_PATH, 'repo_info', f'{lang}_top_star_repos.jsonl')) as f:
        repos_info = ([json.loads(line) for line in f.readlines()])

    commit_urls = []
    for repo in repos_info:
        user_name, proj_name = re.match('(.+)/(.+)', repo["full_name"]).groups()
        repo_path = os.path.join(REPOS_PATH, proj_name)
        # extract all commit urls via git
        commit_ids = get_all_commit_ids(repo_path)
        commit_urls.extend([f'https://github.com/{user_name}/{proj_name}/commit/{commit_id}' for commit_id in commit_ids])

    error_cnt = {}
    filtered_commit_urls = []
    error_cnt_lock = threading.Lock()
    filtered_urls_lock = threading.Lock()
    stop_flag = threading.Event()

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for commit_url in commit_urls:
            if stop_flag.is_set():
                break
            future = executor.submit(lambda url: (
                commit_filter(url),
                filtered_urls_lock.acquire(),
                filtered_commit_urls.append(url),
                filtered_urls_lock.release()
            ) if not stop_flag.is_set() else None, commit_url)
            futures.append((future, commit_url))
        
        for future, commit_url in tqdm(futures):
            if stop_flag.is_set():
                break
            try:
                future.result()
            except Exception as e:
                label = str(e).split(' ')[0]
                if label not in ['1', '2', '3', '4']:
                    print('Unexpected Error:', e)
                    print('Commit url:', commit_url)
                    stop_flag.set()
                    executor.shutdown(wait=False)
                    break
                else:
                    with error_cnt_lock:
                        if label not in error_cnt:
                            error_cnt[label] = 1
                        else:
                            error_cnt[label] += 1
                    
    print(f'{lang} have {len(filtered_commit_urls)} left, survive rate: {len(filtered_commit_urls)/len(commit_urls)*100:.2f}%')
    print('Commit filtered out because:')
    error_dict = {
        "1": "Commit msg contain > 1 edit intention",
        "2": "Commit msg contain non-ascii char",
        "3": "Merge pull request / branch commit",
        "4": "Commit author / committer not real user",
    }
    for error_idx, error_num in error_cnt.items():
        print(f'Rule {error_idx} {error_dict[error_idx]}: {error_num}')

    os.makedirs(os.path.join(ROOT_PATH, 'commit_info'), exist_ok=True)
    with open(os.path.join(ROOT_PATH, f'commit_info/{lang}_filtered_commit_urls.json'), 'w') as f:
        json.dump(filtered_commit_urls, f, indent=4)
    
if __name__ == '__main__':
    lang = 'python'
    clean_commit(lang)  