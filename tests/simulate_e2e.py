import asyncio

import httpx

BASE_URL = "http://localhost:8000/api/v1"


async def main():
    async with httpx.AsyncClient(timeout=300.0) as client:
        print("Creating job...")
        res = await client.post(
            f"{BASE_URL}/reviews",
            json={"user_id": "test_user", "role": "researcher", "topic": "AI Agents", "max_results": 10},
        )
        job = res.json()
        job_id = job["job_id"]
        print(f"Job created: {job_id}")

        while True:
            res = await client.get(f"{BASE_URL}/reviews/{job_id}/status")
            status = res.json()["status"]
            print(f"Status: {status}")
            if status in ["hitl_waiting", "error", "approved", "changes_requested"]:
                break
            await asyncio.sleep(5)

        if status == "hitl_waiting":
            print("Job is hitl_waiting. Submitting review...")
            result_res = await client.get(f"{BASE_URL}/reviews/{job_id}")
            result_data = result_res.json()
            claims = result_data.get("claims", [])
            references = result_data.get("references", [])
            print(f"Extracted {len(claims)} claims and {len(references)} references.")

            # Approve all
            decisions = [{"claim_id": c["claim_id"], "verdict": "supported", "note": ""} for c in claims]
            ref_checks = [{"paper_id": r["paper_id"], "verdict": "valid", "note": ""} for r in references]

            review_res = await client.post(
                f"{BASE_URL}/reviews/{job_id}/review",
                json={
                    "reviewer_id": "rev_1",
                    "role": "reviewer",
                    "decisions": decisions,
                    "reference_checks": ref_checks,
                    "report_decision": "approve",
                    "report_note": "LGTM",
                },
            )
            print("Review submitted.", review_res.status_code)

            # Wait for approved
            while True:
                res = await client.get(f"{BASE_URL}/reviews/{job_id}/status")
                status = res.json()["status"]
                print(f"Status: {status}")
                if status in ["error", "approved", "changes_requested"]:
                    break
                await asyncio.sleep(2)

            # Submit evaluation
            print("Submitting evaluation...")
            eval_res = await client.post(
                f"{BASE_URL}/reviews/{job_id}/evaluation",
                json={
                    "evaluator_id": "rev_1",
                    "manual_minutes": 120,
                    "mvp_minutes": 20,
                    "usefulness_score": 4,
                    "notes": "Good",
                },
            )
            print("Evaluation submitted.", eval_res.status_code)


if __name__ == "__main__":
    asyncio.run(main())
