import requests
import json
import os
import re
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

session = requests.Session()
BASE_URL = "https://ci.viaversion.com/job/"
PROJECTS_DIR = "projects"


def get_projects():
    response = session.get("https://ci.viaversion.com/api/json")
    return [job["name"] for job in response.json()["jobs"]]


def get_artifact_metadata(job_url: str, build_number: int, relative_path: str):
    size = 0
    file_hash = ""
    
    try:
        response = session.head(f"{job_url}/{build_number}/artifact/{relative_path}")
        size = int(response.headers.get("Content-Length", 0))
    except Exception:
        pass
    
    fingerprint_url = f"{job_url}/{build_number}/artifact/{relative_path}/*fingerprint*/"
    response = session.get(fingerprint_url)
    hash_matches = re.findall(r"[0-9a-f]{32}", response.text)
    
    if hash_matches:
        file_hash = hash_matches[0]
    
    return size, file_hash


def get_job(job_url: str, build_number: int):
    response = session.get(f"{job_url}/{build_number}/api/json")
    if response.status_code != 200:
        return None
    
    data = response.json()
    artifacts_metadata = []
    
    for artifact in data["artifacts"]:
        relative_path = artifact["relativePath"]
        size, file_hash = get_artifact_metadata(job_url, build_number, relative_path)
        artifacts_metadata.append({
            "url": f"{job_url}/{build_number}/artifact/{relative_path}",
            "file_name": artifact["fileName"],
            "hash": file_hash,
            "size": size,
        })
    
    artifacts_metadata.sort(key=lambda item: item["size"])
    version = ""
    
    if artifacts_metadata:
        filename = artifacts_metadata[0]["file_name"].removesuffix(".jar")
        parts = filename.split("-")
        if len(parts) > 1:
            version = parts[1]
        if "SNAPSHOT" in filename:
        	items = data["changeSet"]["items"]
        	if items:
        		version = items[0]["commitId"][:7]
    
    return {
        "build_number": build_number,
        "version": version,
        "artifacts": artifacts_metadata,
    }


def get_latest_build_number(name: str):
    response = session.get(f"{BASE_URL}{name}/api/json")
    return response.json()["lastBuild"]["number"]


def fetch_job_json_data(existing_builds: list, name: str, checkpoint: int, latest_build_number: int):
    job_url = f"{BASE_URL}{name}"
    pbar = tqdm(total=latest_build_number - checkpoint, desc=name)
    
    with ThreadPoolExecutor(max_workers=32) as executor:
        futures = {executor.submit(get_job, job_url, number): number for number in range(checkpoint + 1, latest_build_number + 1)}
        
        for future in futures:
            future.add_done_callback(lambda _: pbar.update(1))
        
        new_builds = [future.result() for future in as_completed(futures) if future.result()]
    
    pbar.close()
    return sorted(existing_builds + new_builds, key=lambda item: item["build_number"])


def fetch_job(name: str):
    file_path = os.path.join(PROJECTS_DIR, f"{name}.json")
    
    if os.path.isfile(file_path):
        with open(file_path, "r") as file:
            data = json.load(file)
    else:
        data = {"builds": [], "prev_build_number": 0}
    
    latest_build_number = get_latest_build_number(name)
    prev_build_number = data["prev_build_number"]
    
    data["builds"] = fetch_job_json_data(data["builds"], name, prev_build_number, latest_build_number)
    data["prev_build_number"] = latest_build_number
    
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)


if __name__ == "__main__":
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    
    projects = get_projects()
    for project in projects:
        fetch_job(project)
