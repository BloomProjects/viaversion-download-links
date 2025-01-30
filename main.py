import requests
import json
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import os

session = requests.Session()

def get_projects():
	r = session.get("https://ci.viaversion.com/api/json")
	return [ job["name"] for job in r.json()["jobs"] ]

def get_artifact_metadata(job_url: str, buildNumber: int, relativePath: str):
	r = requests.head(f"{job_url}/{buildNumber}/artifact/{relativePath}")
	size = r.headers["Content-Length"]

	r2 = requests.get(f"{job_url}/{buildNumber}/artifact/{relativePath}/*fingerprint*/")
	file_hash = re.findall(r"[0-9a-f]{32}", r2.text)[0]

	return (size, file_hash)


def get_job(job_url: str, name: str, buildNumber: int):
	r = session.get(f"{job_url}/{buildNumber}/api/json")
 
	if r.status_code != 200:
		return None
 
	data = r.json()
	status = data["result"].lower()
	
	# get artifacts
	artifacts = data["artifacts"]
	artifacts_metadata = []
	for artifact in artifacts:
		relativePath = artifact["relativePath"]
		artifact_metadata = get_artifact_metadata(job_url, buildNumber, relativePath)
		artifact_data = {
			"url": f"{job_url}/{buildNumber}/artifact/{relativePath}",
			"file_name": artifact["fileName"],
			"hash": artifact_metadata[1],
			"size": artifact_metadata[0]
		}

		artifacts_metadata.append(artifact_data)
	artifacts_metadata = sorted(artifacts_metadata, key = lambda item: item["size"])

	# get version
	version = ""

	try:
		if artifacts_metadata:
			filename = artifacts_metadata[0]["file_name"].removesuffix(".jar")
			version = filename.split("-")[1]
		elif "SNAPSHOT" in r.text:
			version = data["changeSet"]["items"][0]["commitId"][:7]
	except Exception as e:
		pass

	return {
		"build_number": buildNumber,
		"version": version,
		"artifacts": artifacts_metadata,
	}
 
def get_latest_build_number(name: str):
	job_url = f"https://ci.viaversion.com/job/{name}"

	r = session.get(f"{job_url}/api/json")
	return r.json()["lastBuild"]["number"]

def fetch_job_json_data(results: list, name: str, checkPoint: int, latestBuildNumber: int):
	new_results = results
	job_url = f"https://ci.viaversion.com/job/{name}"

	pbar = tqdm(total=latestBuildNumber-checkPoint, desc=name)
	with ThreadPoolExecutor(max_workers=16) as executor:
		futures = {executor.submit(lambda number: get_job(job_url, name, number), number): number for number in range(checkPoint+1, latestBuildNumber+1)}

		for future in futures:
			future.add_done_callback(lambda _: pbar.update(1))
   
		new_results += [future.result() for future in as_completed(futures)]
	new_results = [item for item in new_results if item]
	new_results = sorted(new_results, key = lambda item: item["build_number"])
	pbar.close()

	return new_results

def fetch_job(name: str):
	file_path = f"projects/{name}.json"

	if os.path.isfile(file_path):
		with open(file_path, "r") as f:
			data = json.load(f)
	else:
		data = {
			"builds": [],
			"prev_build_number": 0
		}

	latestBuildNumber = get_latest_build_number(name)
	prevBuildNumber = data["prev_build_number"]
	builds = data["builds"]
	data["builds"] = fetch_job_json_data(builds, name, prevBuildNumber, latestBuildNumber)
	data["prev_build_number"] = latestBuildNumber

	with open(file_path, "w") as f:
		json.dump(data, f, indent=4)

if __name__ == '__main__':
	if not os.path.isdir("projects"):
		os.mkdir("projects")

	projects = get_projects()

	for project in projects:
		fetch_job(project)