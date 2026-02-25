# This script is used to test different system under test components
import os
import json
import random

from .utils import *
from .commit import Commit
from dotenv import load_dotenv

current_path = os.path.abspath(os.path.dirname(__file__))
root_path = os.path.abspath(os.path.join(current_path, "../../"))
load_dotenv(dotenv_path=os.path.join(root_path, ".config"))
REPOS_DIR = os.getenv("REPOS_DIR") # this directory should be the absolute path to the repository directory
os.makedirs(REPOS_DIR, exist_ok=True)
COMMIT = None

if __name__ == "__main__":
    # Step 1: recover the simulation status
    sut="TRAE"
    commit_url = "https://github.com/getredash/redash/commit/ab72531889f47f8e3d653849ebdf97cac1455a47"
    repos_dir = "/Users/bytedance/Downloads/tmp"
    repo_dir = os.path.join(repos_dir, "redash")
    COMMIT = Commit(commit_url, repos_dir, sut)
    COMMIT.update_edit_status(0, "simulated", True)
    COMMIT.update_allowed_as_next()

    # Step 2: test corresponding SUT component under given simulation status
    from systemUnderTest.TRAE.utils import *
    # Write your code to test