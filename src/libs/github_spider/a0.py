import os
import time

from dotenv import load_dotenv
from a1_crawl import crawl
from a2_clean_commit_info import clean_commit
from a3_clean_edit_info import clean_edit

current_path = os.path.abspath(os.path.dirname(__file__))
root_path = os.path.abspath(os.path.join(current_path, "../../../"))
load_dotenv(dotenv_path=os.path.join(root_path, ".config"))
GITHUB_TOKENS = os.getenv("GITHUB_TOKENS").split(',')
CURR_TOKEN_IDX = 0
GITHUB_TOKENS_RST_TIME = [time.time()-3600 for _ in range(len(GITHUB_TOKENS))]
REPOS_PATH = os.getenv("REPOS_DIR")
ROOT_PATH = current_path

if __name__ == '__main__':
    lang = 'python' 
    num_of_repo = 10 

    # # Step 1: get repos, commits and clone to local
    # crawl(lang, num_of_repo)
    
    # # Step 2: filter commit based on commit information
    # clean_commit(lang)
    
    # Step 3: filter commit based on edit information
    clean_edit(lang)