# This script is used to crawl top star open source projects from GitHub by language
# 1. It crawl the top k repositories' information, save to {ROOT_PATH}/repo_info/{lang}_top_star_repos.jsonl
# 2. For each repository, it crawl all its commits' information, save to {ROOT_PATH}/commit_info/{lang}_commit_info.jsonl
# 3. For each repository, it git clone the project to {ROOT_PATH}/repos/
import os
import re
import json
import time
import random
import requests
import jsonlines
import subprocess
from tqdm import tqdm

from proxies_pool import proxy_list
from user_agent_pool import user_agents    
from concurrent.futures import ThreadPoolExecutor

def get_response(request_url, params=None):
    from a0 import CURR_TOKEN_IDX, GITHUB_TOKENS, GITHUB_TOKENS_RST_TIME
    MAX_RETRIES = 10
    headers = {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Authorization':'token '+ GITHUB_TOKENS[CURR_TOKEN_IDX],
        'Accept-Encoding': 'gzip,deflate,sdch',
        'Accept-Language': 'zh-CN,zh;q=0.8'
    }
    for i in range(MAX_RETRIES):
        proxy = random.choice(proxy_list)
        try:
            r = requests.get(request_url, params, headers=headers,
                            proxies={"http": proxy}, timeout=40)
        except requests.exceptions.RequestException as e:
            if i < MAX_RETRIES - 1:
                continue
            raise Exception(e)

        if r.status_code == 200:
            break # if successfully get response, break the loop and return content
        else:
            if r.status_code == 403: # if the request budget has been used up, sleep for 1 hour
                print("==> 403 Forbidden, the request budget has been used up")
                print("==> Switch to another token")
                GITHUB_TOKENS_RST_TIME[CURR_TOKEN_IDX] = time.time()
                CURR_TOKEN_IDX = (CURR_TOKEN_IDX + 1) % len(GITHUB_TOKENS)
                headers = { # update the headers
                    'User-Agent': random.choice(user_agents),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Authorization':'token '+ GITHUB_TOKENS[CURR_TOKEN_IDX],
                    'Accept-Encoding': 'gzip,deflate,sdch',
                    'Accept-Language': 'zh-CN,zh;q=0.8'
                }
                if GITHUB_TOKENS_RST_TIME[CURR_TOKEN_IDX] + 3600 > time.time():
                    print("==> All tokens have been used up, sleep until next token is available")
                    time.sleep(3600-(time.time()-GITHUB_TOKENS_RST_TIME[CURR_TOKEN_IDX])+10)
            else: # other errors, sleep for 1 second
                time.sleep(1)
            if i == MAX_RETRIES - 1: # if all retries failed, raise error
                raise ConnectionError(f"Cannot connect to website: {request_url}, status code: {r.status_code}")
    return r.content

def get_all_response(request_url, params=None):
    '''
    Regardless of the number of pages and the request page index, get all the response
    '''
    if params == None:
        params = {
            "per_page": '100', 
            "page": "1"
        }
    all_d = []
    per_page = int(params['per_page'])
    params['page'] = 1
    while True:
        content = get_response(request_url, params)
        d = json.loads(content)
        all_d.extend(d)
        if len(d) < per_page:
            break
        else:
            params['page'] += 1
            time.sleep(1)
    return all_d

def get_small_response(request_url, params=None):
    '''
    only get 1 page with 5 items, for test, remove it later
    '''
    if params == None:
        params = {
            "per_page": '5', 
            "page": "1"
        }
    content = get_response(request_url, params)
    d = json.loads(content)
    return d

def get_repos(lang, repo_num):
    # get the top star repos' information of this language
    repos = []
    for page_idx in range(1, repo_num // 100 + 2):
        request_url = "https://api.github.com/search/repositories"
        params = {
            "q": "language:{} stars:>500".format(lang),
            "page": "{}".format(str(page_idx)),
            "per_page": "100",
            "sort": "stars",
            "order": "desc",
            "license": "mit",
        }
        content = get_response(request_url, params)
        d = json.loads(content)
        items = d["items"]

        for item in items:
            title = item["full_name"]
            url = item["html_url"]
            date_time = item["updated_at"]
            description = item["description"]
            stars = item["stargazers_count"]
            line = u"* [{title}]({url})|{stars}|{date_time}|:\n {description}\n". \
                format(title=title, date_time=date_time, url=url, description=description, stars=stars)
            print(line)
            repos.append(item)
            if len(repos) >= repo_num:
                break
    if len(repos) == 0:
        raise Exception("No repos found")
    return repos

def git_clone(user_name, proj_name):
    # Check if this repo has been downloaded
    from a0 import REPOS_PATH, GITHUB_TOKENS, CURR_TOKEN_IDX
    
    if not os.path.exists(REPOS_PATH):
        os.mkdir(REPOS_PATH)
    if os.path.exists(os.path.join(REPOS_PATH, proj_name)):
        result = subprocess.run(
            "git remote show origin | grep 'HEAD branch'",
            shell=True,
            text=True,
            capture_output=True,
            check=True,
            cwd=os.path.normpath(os.path.join(REPOS_PATH, proj_name))
        )
        branch_name = result.stdout.split(":")[1].strip()
        try:
            fetch_command = ["git", "fetch", "origin"]
            subprocess.run(fetch_command, check=True, cwd=os.path.join(REPOS_PATH, proj_name))
            # Run the Git pull command
            reset_command = ["git", "reset", "--hard", f"origin/{branch_name}"]
            subprocess.run(reset_command, check=True, cwd=os.path.join(REPOS_PATH, proj_name))
        except:
            raise Exception(f"==> Pulling {user_name}/{proj_name} failed")
    else: # if not, download the whole repo of the latest version
        clone_url = f"https://{GITHUB_TOKENS[CURR_TOKEN_IDX]}@github.com/{user_name}/{proj_name}.git"
        try:
            git_clone_command = ["git", "clone", clone_url]
            # Run the Git clone command
            subprocess.run(git_clone_command, check=True, cwd=REPOS_PATH)
        except:
            raise Exception(f"==> Downloading {user_name}/{proj_name} from {clone_url} failed")
    
def crawl(lang, repo_num):
    from a0 import ROOT_PATH
    # ---------------------- Get the top star repo's name ----------------------
    if not os.path.exists(ROOT_PATH+"/repo_info"):
        os.mkdir(ROOT_PATH+"/repo_info")
    print("==> Starting to get repos of %s ..." % lang)
    if os.path.exists(ROOT_PATH+f"/repo_info/{lang}_top_star_repos.jsonl"):    # if have recorded repos before
        # open recorded repo info
        with jsonlines.open(ROOT_PATH+f"/repo_info/{lang}_top_star_repos.jsonl") as reader:
            print(f"==> {lang}_top_star_repos.jsonl exists, read from local")
            repos = list(reader)
        if len(repos) < repo_num: # if the number of repo has not been satisfied
            repos = get_repos(lang, repo_num) # get the desired number of repos
            # save repo info
            with jsonlines.open(ROOT_PATH+f"/repo_info/{lang}_top_star_repos.jsonl", 'w') as writer:
                writer.write_all(repos)
    else:
        repos = get_repos(lang, repo_num) # get the desired number of repos
        # save repo info
        with jsonlines.open(ROOT_PATH+f"/repo_info/{lang}_top_star_repos.jsonl", 'w') as writer:
            writer.write_all(repos)
    print(f"==> Get {str(len(repos[:repo_num]))} repos of {lang}")

    with open(os.path.join(ROOT_PATH, 'repo_info', f'{lang}_top_star_repos.jsonl')) as f:
        repos_info = ([json.loads(line) for line in f.readlines()])
    
    repos_to_clone = repos_info[:repo_num]
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for repo in repos_to_clone:
            title = repo["full_name"]
            user_name, proj_name = re.match('(.+)/(.+)', title).groups()
            future = executor.submit(git_clone, user_name, proj_name)
            futures.append(future)
        
        for future in tqdm(futures, desc='Git clone repos'):
            future.result()
        
if __name__ == '__main__':
    start = time.time()
    lang = 'python' # java, python, typescript, go
    num_of_repo = 100 # the number of repo to be crawled # debug
    crawl(lang, num_of_repo)
    end = time.time()
    print(f'==> Time elapsed: {end - start} seconds')