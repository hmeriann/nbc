'''
We would like to know if extensions can be installed and loaded on fresh builds.

'''
import argparse
import duckdb
import glob
import os
import pandas
import random
import re
import subprocess
import sys
import tabulate
from shared_functions import fetch_data

GH_REPO = os.environ.get('GH_REPO', 'duckdb/duckdb')
ACTIONS = ["INSTALL", "LOAD"]
EXT_WHICH_DOESNT_EXIST = "EXT_WHICH_DOESNT_EXIST"

parser = argparse.ArgumentParser()
parser.add_argument("--nightly_build")
parser.add_argument("--architecture")
parser.add_argument("--run_id")
parser.add_argument("--runs_on")
parser.add_argument("--config")

args = parser.parse_args()

nightly_build = args.nightly_build
architecture = args.architecture if nightly_build == 'Python' else args.architecture.replace("-", "/") # linux-aarch64 => linux/aarch64 for docker
run_id = args.run_id
runs_on = args.runs_on # linux-latest
config = args.config # ext/config/out_of_tree_extensions.cmake

def list_extensions(config) :
    with open(config, "r") as file:
        content = file.read()
    # matching each word after `load(`
    pattern = r"duckdb_extension_load\(\s*([^\s,)]+)"
    matches = re.findall(pattern, content)
    return matches

def get_full_sha(run_id):
    gh_headSha_command = [
        "gh", "run", "view",
        run_id,
        "--repo", GH_REPO,
        "--json", "headSha",
        "-q", ".headSha"
    ]
    full_sha = subprocess.run(gh_headSha_command, check=True, text=True, capture_output=True).stdout.strip()
    return full_sha

def verify_version(tested_binary, file_name):
    full_sha = get_full_sha(run_id)
    pragma_version = [ tested_binary, "--version" ]
    short_sha = subprocess.run(pragma_version, text=True, capture_output=True).stdout.strip().split()[-1]
    if not full_sha.startswith(short_sha):
        print(f"""
        Version of { nightly_build } tested binary doesn't match to the version that triggered the build.
        - Version triggered the build: { full_sha }
        - Downloaded build version: { short_sha }
        """)
        with open(file_name, 'w') as f:
            f.write(f"""
            Version of { nightly_build } tested binary doesn't match to the version that triggered the build.
            - Version triggered the build: { full_sha }
            - Downloaded build version: { short_sha }
            """)
        return False
    print(f"""
    Versions of { nightly_build } build match:
    - Version triggered the build: { full_sha }
    - Downloaded build version: { short_sha }
    """)
    return True

def test_extensions(tested_binary, file_name):
    extensions = list_extensions(config)
    counter = 0 # to add a header to list_failed_ext_nightly_build_architecture.csv only once

    for ext in extensions:
        select_installed = [
            tested_binary,
            "-csv",
            "-noheader",
            "-c",
            f"SELECT installed FROM duckdb_extensions() WHERE extension_name='{ ext }';"
        ]
        result=subprocess.run(select_installed, text=True, capture_output=True)

        is_installed = result.stdout.strip()
        if is_installed == 'false':
            for action in ACTIONS:
                print(f"{ action }ing { ext }...")
                install_ext = [
                    tested_binary, "-c",
                    f"{ action } '{ ext }';"
                ]
                try:
                    result = subprocess.run(install_ext, text=True, capture_output=True)
                    if result.stderr:
                        print(f"{ action } had failed with following error:\n{ result.stderr.strip() }")
                        with open(file_name, "a") as f:
                            if counter == 0:
                                f.write("nightly_build,architecture,runs_on,version,extension,failed_statement\n")
                                counter += 1
                            f.write(f"{ nightly_build },{ architecture },{ runs_on },,{ ext },{ action }\n")

                except subprocess.CalledProcessError as e:
                    print(f"Error running command for extesion { ext }: { e }")
                    print(f"stderr: { e.stderr }")
    print(f"Trying to install a non-ecisting extension in {nightly_build}...")
    result = subprocess.run([ tested_binary, "-c", "INSTALL", f"'{ EXT_WHICH_DOESNT_EXIST }'"], text=True, capture_output=True)
    if result.stderr:
        print(f"Attempt to install a non-existing extension resulted with error, as expected: { result.stderr }")
    else:
        print(f"Unexpected extension with name { EXT_WHICH_DOESNT_EXIST } had been installed.")
        f.write(f"Unexpected extension with name { EXT_WHICH_DOESNT_EXIST } had been installed.")

def main():
    file_name = "list_failed_ext_{}_{}.csv".format(nightly_build, architecture.replace("/", "-"))
    counter = 0 # to write only one header per table
    if nightly_build == 'Python':
        verify_and_test_python(file_name, counter, run_id, architecture)
    else:
        path_pattern = os.path.join("duckdb_path", "duckdb*")
        matches = glob.glob(path_pattern)
        if matches:
            tested_binary = os.path.abspath(matches[0])
            print(f"Found binary: { tested_binary }")
        else:
            raise FileNotFoundError(f"No binary matching { path_pattern } found in duckdb_path dir.")
        print("VERIFY BUILD SHA")
        if verify_version(tested_binary, file_name):
            print("TEST EXTENSIONS")
            test_extensions(tested_binary, file_name)
        print("FINISH")

if __name__ == "__main__":
    main()