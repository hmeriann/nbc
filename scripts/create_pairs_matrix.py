'''
We would like to run benchmarks comparing 
    - `current main` with `a week ago main`, (1)
    - `current version of the latest release` with `a week ago version of the latest release` (2),
    - `current main` with 
        `current version of the latest release` and (3)
        `current version of the previous release` (4)

The script finds latest and previous versions in current heads (`git ls-remote --heads`) and creates last pairs (3), (4) from it.
It takes "new_sha" for `main` and for `latest release` in previous version of json file and creates pairs (1), (2).
It doesn't create pair (2), when there is no "new_sha" for `latest release` in previous version of json file.
In the end it writes pairs to `duckdb_previous_version_pairs.json` file. The file is used to create a matrix for regression tests run.

If there is a `duckdb_curr_version_main.txt` on the machine, it will create 5th pair `curr-main - old-main` with the
SHA from the file and removes that file. So the next time it will be creating 4 unique pairs as described above.

Contents of the `duckdb_previous_version_pairs.json` look like this:
[
    {
        "new_name": "main",
        "new_sha": "latest main SHA",
        "old_name": "main",
        "old_sha": "a week ago main SHA"
    },
    {
        "new_name": "main",
        "new_sha": "latest main SHA",
        "old_name": "v1.2-histrionicus",
        "old_sha": "latest v1.2-histrionicus SHA"
    },
    {
        "new_name": "v1.2-histrionicus",
        "new_sha": "latest v1.2-histrionicus SHA",
        "old_name": "v1.2-histrionicus",
        "old_sha": "a week ago v1.2-histrionicus SHA"
    },
    {
        "new_name": "main",
        "new_sha": "latest main SHA",
        "old_name": "v1.1-eatoni",
        "old_sha": "latest v1.1-eatoni SHA"
    }
]
Names in pairs are starting with "old" and "new" because we use `--old` and `--new` to pass values to the `regression_runner`
'''

import subprocess
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta

PAIR_FILE = "duckdb_previous_version_pairs.json"
TXT_FILE = "duckdb_curr_version_main.txt"
PARENT_DIR = os.path.dirname(os.getcwd())
PAIRS_FILE_PATH = os.path.join(PARENT_DIR, PAIR_FILE)
GH_REPO = "duckdb/duckdb"

def maybe_remove_txt_file():
    txt_file_path = os.path.join(PARENT_DIR, TXT_FILE)
    if os.path.isfile(txt_file_path):
        with open(txt_file_path, "r") as f:
            old_main_sha = f.read()
        os.remove(txt_file_path)
        return old_main_sha

def git_checkout(branch_name):
    subprocess.run(["git", "checkout", branch_name])

def git_fetch(branch_name):
    subprocess.run(["git", "fetch", "origin", f"{branch_name}"])

def get_current_sha():
    result = subprocess.run(["git", "rev-list", "-1", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip()
    
def get_sha_week_ago(branch_name):
    date_week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    result = subprocess.run(["git", "rev-list", "-1", f"--before={date_week_ago}", f"{branch_name}"], capture_output=True, text=True)
    return result.stdout.strip()

def check_its(branch_name):
    result = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() == branch_name

def list_branches(repo):
    result = subprocess.run(["gh", "api", f"repos/{GH_REPO}/branches", "--paginate", "--jq", ".[].name"], capture_output=True, text=True)
    return result.stdout.strip().splitlines()

def hardcode_versions():
    branches = list_branches(GH_REPO)
    main_branch = branches[0]
    release_branch = branches[-1]
    previous_release_branch = branches[-2]
    pairs = []

    git_checkout(main_branch)
    git_fetch(main_branch)
    curr_main_sha = get_current_sha()
    old_main_sha = get_sha_week_ago(main_branch)
    pairs.append({
        "new_name": main_branch,
        "new_sha": curr_main_sha,
        "old_name": main_branch,
        "old_sha": old_main_sha
    })
    
    git_fetch(release_branch)
    git_checkout(release_branch)
    curr_release_sha = get_current_sha()
    old_release_sha = get_sha_week_ago(release_branch)
    pairs.append({
        "new_name": main_branch,
        "new_sha": curr_main_sha,
        "old_name": release_branch,
        "old_sha": curr_release_sha
    })
    if len(old_release_sha) > 0:
        pairs.append({
            "new_name": release_branch,
            "new_sha": curr_release_sha,
            "old_name": release_branch,
            "old_sha": old_release_sha
        })

    git_fetch(previous_release_branch)
    git_checkout(previous_release_branch)
    curr_previous_release_sha = get_current_sha()
    pairs.append({
        "new_name": main_branch,
        "new_sha": curr_main_sha,
        "old_name": previous_release_branch,
        "old_sha": curr_previous_release_sha
    })
    return pairs

def main():
    maybe_remove_txt_file()
    unique_pairs = hardcode_versions()
    print(unique_pairs)
    with open(PAIRS_FILE_PATH, "w") as f:
        json.dump(unique_pairs, f, indent=4)

if __name__ == "__main__":
    main()