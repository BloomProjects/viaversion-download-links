import requests
import json
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import os

session = requests.Session()

def get_projects():
	r = session.get("https://ci.viaversion.com/api/json")
	projects = [ {"name": job["name"], "url": job["url"]} for job in r.json()["jobs"] ]
	return projects

def get_job(job_url: str, name: str, buildNumber: int):
	r = session.get(f"{job_url}/{buildNumber}/api/json")
 
	if r.status_code != 200:
		return {
			"build_number": buildNumber,
			"version": "",
			"artifact": ""
		}
 
	data = r.json()
	realArtifact = None
 
	for artifact in data["artifacts"]:
		if "javadocs" not in artifact["relativePath"] and "sources" not in artifact:
			realArtifact = artifact
			break
   
	if not realArtifact:
		return {
			"build_number": buildNumber,
			"version": "",
			"artifact": ""
		}

	relativePath = realArtifact["relativePath"]
	artifact_url = f"{job_url}/{buildNumber}/artifact/{relativePath}".strip()
 
	version = realArtifact["fileName"].removeprefix(f"{name}-").removesuffix(".jar")
 
	if "SNAPSHOT" in relativePath:
		try:
			version = re.findall(r"[0-9a-f]{40}", r.text)[0][:7]
		except Exception as e:
			pass
  
	return {
		"build_number": buildNumber,
		"version": version,
		"artifact": artifact_url
	}
 

def get_latest_build_number(name: str):
	job_url = f"https://ci.viaversion.com/job/{name}"

	r = session.get(f"{job_url}/api/json")
	return r.json()["nextBuildNumber"]

def fetch_job_json_data(results: list, name: str, checkPoint: int, latestBuildNumber: int):
	job_url = f"https://ci.viaversion.com/job/{name}"

	pbar = tqdm(total=latestBuildNumber-checkPoint-1, desc=name)

	with ThreadPoolExecutor(max_workers=32) as executor:
		futures = {executor.submit(lambda number: get_job(job_url, name, number), number): number for number in range(checkPoint+1, latestBuildNumber)}

		for future in futures:
			future.add_done_callback(lambda _: pbar.update(1))
   
		results += [future.result() for future in as_completed(futures)]
	
	pbar.close()


if __name__ == '__main__':
	if os.path.isfile("builds.json"):
		with open("builds.json", "r") as f:
			data = json.load(f)
	else:
		data = {}

	projects = get_projects()

	for project in projects:
		name = project["name"]

		if name not in data:
			data[name] = {
				"builds": [],
				"checkPoint": 0
			}

		checkPoint = get_latest_build_number(name)
		fetch_job_json_data(data[name]["builds"], name, data[name]["checkPoint"], checkPoint)
		data[name]["builds"] = sorted(data[name]["builds"], key = lambda item: item["build_number"])
		data[name]["checkPoint"] = checkPoint
  
	with open("builds.json", "w") as f:
		json.dump(data, f, indent=4)