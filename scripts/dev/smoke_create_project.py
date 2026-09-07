import asyncio
import httpx
import traceback

async def main():
    try:
        async with httpx.AsyncClient(base_url="http://localhost:8000/api/v1") as client:
            resp = await client.post("/auth/session", json={"bootstrap_token": "researcher:test_user_1"})
            print("Bootstrap:", resp.status_code)
            
            resp = await client.post("/projects", json={"name": "Test Project", "description": "A test project"})
            print("Create Project:", resp.status_code)
            project_id = resp.json()["project"]["project_id"]
            
            resp = await client.get(f"/projects/{project_id}")
            print("Get Project:", resp.status_code, resp.text[:100])
            
            resp = await client.get(f"/projects/{project_id}/reviews")
            print("Get Reviews:", resp.status_code, resp.text[:100])

            resp = await client.get(f"/projects/{project_id}/report-versions")
            print("Get Versions:", resp.status_code, resp.text[:100])
    except Exception as e:
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
