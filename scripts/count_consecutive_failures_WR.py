import duckdb
import argparse
import pandas as pd
import tabulate
import subprocess
import json
import datetime
import os
import glob
import re
from collections import defaultdict

GH_REPO = 'duckdb/duckdb'
REPORT_FILE = f"nightly_builds_status.md"
CURR_DATE = datetime.datetime.now().strftime('%Y-%m-%d')
has_no_artifacts = ('Python', 'Julia', 'Swift', 'SwiftRelease')

parser = argparse.ArgumentParser()
parser.add_argument("GH_TOKEN")
args = parser.parse_args()
GH_TOKEN = args.GH_TOKEN

def get_value_for_key(key, nightly_build):
    value = duckdb.sql(f"""
        SELECT { key } 
        FROM read_json('{ nightly_build }.json') 
        WHERE status = 'completed' 
        ORDER BY createdAt 
        DESC LIMIT 1;
        """).fetchone()[0]
    return value
    
def fetch_data(command, f_output): # saves command execution results into a file
    data = open(f_output, "w")
    try:
        subprocess.run(command, stdout=data, stderr=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e.stderr}")

# count consecutive failures
def count_consecutive_failures(nightly_build, input_file, url, con):
    input_file = f"{ nightly_build }.json"
    con.execute(f"""
        CREATE OR REPLACE TABLE 'gh_run_list_{ nightly_build }' AS (
            SELECT *
            FROM '{ input_file }')
            ORDER BY createdAt DESC
    """)
    latest_success_rowid = con.execute(f"""
        SELECT rowid
        FROM 'gh_run_list_{ nightly_build }'
        WHERE conclusion = 'success'
        ORDER BY createdAt DESC
    """).fetchone()
    count_consecutive_failures = latest_success_rowid[0] if latest_success_rowid else -1 # when -1 then all runs in the json file have conclusion 'failure'
    return count_consecutive_failures

def create_tables_for_report(nightly_build, con):
    input_file = f"{ nightly_build }.json"

    if nightly_build not in has_no_artifacts:
        con.execute(f"""
            CREATE OR REPLACE TABLE 'steps_{ nightly_build }' AS (
                SELECT * FROM read_json('{ nightly_build }_jobs.json')
            )
        """)
        con.execute(f"""
                CREATE OR REPLACE TABLE 'artifacts_{ nightly_build }' AS (
                    SELECT * FROM read_json('{ nightly_build }_artifacts.json')
                );
            """)
        # check if the artifatcs table is not empty
        artifacts_count = con.execute(f"SELECT list_count(artifacts) FROM 'artifacts_{ nightly_build }';").fetchone()[0]
        if artifacts_count > 0:
            con.execute(f"""
                CREATE OR REPLACE TABLE 'artifacts_per_jobs_{ nightly_build }' AS (
                    SELECT
                        t1.job_name AS "Build (Architecture)",
                        t1.conclusion AS "Conclusion",
                        t2.name AS "Artifact",
                        t2.updated_at AS "Uploaded at"
                    FROM (
                        SELECT
                            job_name,
                            steps.name step_name, 
                            steps.conclusion conclusion,
                            steps.startedAt startedAt
                        FROM (
                            SELECT
                                unnest(steps) steps,
                                job_name 
                            FROM (
                                SELECT
                                    unnest(jobs)['steps'] steps,
                                    unnest(jobs)['name'] job_name 
                                FROM 'steps_{ nightly_build }'
                                )
                            )
                        WHERE steps['name'] LIKE '%upload%'
                        ORDER BY 
                            conclusion DESC,
                            startedAt
                        ) t1
                    POSITIONAL JOIN (
                        SELECT
                            art.name,
                            art.expires_at expires_at,
                            art.updated_at updated_at
                        FROM (
                            SELECT
                                unnest(artifacts) art
                            FROM 'artifacts_{ nightly_build }'
                            )
                        ORDER BY expires_at
                        ) as t2
                    );
                """)
        else:
            con.execute(f"""
                CREATE OR REPLACE TABLE 'artifacts_per_jobs_{ nightly_build }' AS (
                    SELECT job_name, conclusion 
                    FROM (
                        SELECT unnest(j['steps']) steps, j['name'] job_name, j['conclusion'] conclusion 
                        FROM (
                            SELECT unnest(jobs) j 
                            FROM 'steps_{ nightly_build }'
                            )
                        ) 
                    WHERE steps['name'] LIKE '%upload-artifact%'
                    )
                """)

def create_build_report(nightly_build, con):
    input_file = f"{ nightly_build }.json"
    url= con.execute(f"SELECT url FROM '{ input_file }'").fetchone()[0]
    failures_count = count_consecutive_failures(nightly_build, input_file, url, con)

    with open(REPORT_FILE, 'a') as f:
        if failures_count == 0:
            f.write(f"\n## { nightly_build }\n")
            f.write(f"### { nightly_build } nightly-build has succeeded.\n")            
            f.write(f"Latest run: [ Run Link ]({ url })\n")

        else:
            # failures count = -1 means all runs in the json file have conclusion = 'failure' so we need to update its value
            # we count all runs and do not add a last successfull run link to the report
            if failures_count == -1:
                failures_count = con.execute(f"""
                    SELECT
                        count(*)
                    FROM 'gh_run_list_{ nightly_build }'
                    WHERE conclusion = 'failure'
                """).fetchone()[0]
        
            total_count = con.execute(f"""
                SELECT
                    count(*)
                FROM 'gh_run_list_{ nightly_build }'
            """).fetchone()[0]

            f.write(f"## { nightly_build }\n")            
            f.write(f"### { nightly_build } nightly-build has not succeeded the previous **{ failures_count }** times.\n")
            if failures_count < total_count:
                tmp_url = con.execute(f"""
                    SELECT
                        url
                    FROM 'gh_run_list_{ nightly_build }'
                    WHERE conclusion = 'success'
                    ORDER BY createdAt DESC
                """).fetchone()
                latest_success_url = tmp_url[0] if tmp_url else ''
                f.write(f"Latest successfull run: [ Run Link ]({ latest_success_url })\n")

            f.write(f"\n#### Failure Details\n")
            failure_details = con.execute(f"""
                SELECT
                    conclusion as "Conclusion",
                    createdAt as "Created at",
                    url as "URL"
                FROM 'gh_run_list_{ nightly_build }'
                WHERE conclusion = 'failure'
                ORDER BY createdAt DESC
                LIMIT { failures_count }
            """).df()
            f.write(failure_details.to_markdown(index=False))
            
        # check if the artifatcs table is not empty
        if nightly_build not in has_no_artifacts:
            f.write(f"\n#### Workflow Artifacts\n")
            artifacts_per_job = con.execute(f"""
                SELECT * FROM 'artifacts_per_jobs_{ nightly_build }';
                """).df()
            f.write(artifacts_per_job.to_markdown(index=False))
        else:
            f.write(f"**{ nightly_build }** run doesn't upload artifacts.\n\n")
    
def main():
    con = duckdb.connect('run_info_tables.duckdb')
    # list all nightly-build runs on current date
    gh_run_list_file = f"GH_run_list.json"
    gh_run_list_command = [
        "gh", "run", "list",
        "--repo", GH_REPO,
        "--event", "repository_dispatch",
        "--created", CURR_DATE,
        "-L", "50",
        "--json", "status,conclusion,url,name,createdAt,databaseId,headSha",
        "--jq", '.[] | select(.name == "Android" or .name == "Julia" or .name == "LinuxRelease" or .name == "OSX" or .name == "Pyodide" or .name == "Python" or .name == "R" or .name == "Swift" or .name == "SwiftRelease" or .name == "DuckDB-Wasm extensions" or .name == "Windows")'
    ]
    fetch_data(gh_run_list_command, gh_run_list_file)
    result = con.execute(f"SELECT name FROM '{ gh_run_list_file }';").fetchall()
    nightly_builds = [row[0] for row in result]
    # create complete report
    for nightly_build in nightly_builds:
        gh_run_list_file = f"{ nightly_build }.json"
        runs_command = [
                "gh", "run", "list",
                "--repo", GH_REPO,
                "--event", "repository_dispatch",
                "--workflow", f"{ nightly_build }",
                "--json", "status,conclusion,url,name,createdAt,databaseId,headSha"
            ]
        fetch_data(runs_command, gh_run_list_file)
        run_id = get_value_for_key('databaseId', nightly_build)
        jobs_file = f"{ nightly_build }_jobs.json"
        jobs_command = [
                "gh", "run", "view",
                "--repo", GH_REPO,
                f"{ run_id }",
                "--json", "jobs"
            ]
        fetch_data(jobs_command, jobs_file)
        artifacts_file = f"{ nightly_build }_artifacts.json"
        artifacts_command = [
                "gh", "api",
                f"repos/{ GH_REPO }/actions/runs/{ run_id }/artifacts"
            ]
        fetch_data(artifacts_command, artifacts_file)

        create_tables_for_report(nightly_build, con)
        create_build_report(nightly_build, con)
    con.close()

if __name__ == "__main__":
    main()