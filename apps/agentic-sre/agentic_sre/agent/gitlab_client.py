import httpx


class GitLabClient:
    def __init__(
        self,
        base_url: str,
        read_token: str,
        write_token: str,
        project_id: str,
        public_url: str | None = None,
        project_path: str = "shop/day2-demo",
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.read_token = read_token
        self.write_token = write_token
        self.project_id = project_id
        self.public_url = (public_url or base_url).rstrip("/")
        self.project_path = project_path
        self._client = client or httpx.Client(timeout=10.0, trust_env=False)

    def _request(self, method: str, path: str, *, write: bool = False, **kwargs) -> dict | list:
        token = self.write_token if write else self.read_token
        response = self._client.request(
            method,
            self.base_url + path,
            headers={"PRIVATE-TOKEN": token},
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def list_commits(self) -> list:
        return self._request("GET", f"/api/v4/projects/{self.project_id}/repository/commits")

    def list_merge_requests(self) -> list:
        return self._request("GET", f"/api/v4/projects/{self.project_id}/merge_requests")

    def list_pipelines(self) -> list:
        return self._request("GET", f"/api/v4/projects/{self.project_id}/pipelines")

    def list_deployments(self) -> list:
        return self._request("GET", f"/api/v4/projects/{self.project_id}/deployments")

    def open_revert_mr(self, *, sha: str, ref: str, source_branch: str, target_branch: str, title: str, description: str) -> dict:
        return self._request(
            "POST",
            f"/api/v4/projects/{self.project_id}/merge_requests",
            write=True,
            json={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
                "labels": "incident,revert",
            },
        )

    def commit_url(self, sha: str) -> str:
        return f"{self.public_url}/{self.project_path}/-/commit/{sha}"
