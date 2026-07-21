"""Run reproducible local LM Studio authoring trials without repairing responses."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    parser.add_argument("--model", default="qwen2.5-coder-7b-instruct")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=25_000)
    parser.add_argument("--timeout-seconds", type=int, default=7_200)
    return parser.parse_args()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    prompt_template = args.prompt.read_text(encoding="utf-8")
    case_template = args.case.read_text(encoding="utf-8")
    if "[PERSON_AND_CASE_DESCRIPTION]" not in prompt_template:
        raise ValueError("Prompt placeholder [PERSON_AND_CASE_DESCRIPTION] not found")
    if "[GENERATION_TIMESTAMP]" not in case_template:
        raise ValueError("Case placeholder [GENERATION_TIMESTAMP] not found")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    experiment_started = datetime.now(ZoneInfo("Europe/Rome")).isoformat(timespec="seconds")
    metadata: dict[str, object] = {
        "experimentStartedAt": experiment_started,
        "endpoint": f"{args.base_url}/v1/chat/completions",
        "model": args.model,
        "promptPath": str(args.prompt).replace("\\", "/"),
        "promptSha256": hashlib.sha256(prompt_template.encode("utf-8")).hexdigest(),
        "casePath": str(args.case).replace("\\", "/"),
        "caseSha256": hashlib.sha256(case_template.encode("utf-8")).hexdigest(),
        "parameters": {
            "temperature": 0.2,
            "top_p": 0.9,
            "top_k": 40,
            "max_tokens": args.max_tokens,
            "seeds": [101 + index * 101 for index in range(args.runs)],
        },
        "manualEdits": False,
        "repairAttempts": 0,
        "runs": [],
    }
    write_json(args.output_dir / "generation-metadata.json", metadata)

    endpoint = f"{args.base_url}/v1/chat/completions"
    for index in range(args.runs):
        run_number = index + 1
        seed = 101 + index * 101
        run_dir = args.output_dir / f"run-{run_number}"
        run_dir.mkdir(parents=True, exist_ok=True)
        generated_at = datetime.now(ZoneInfo("Europe/Rome")).isoformat(timespec="seconds")
        case_text = case_template.replace("[GENERATION_TIMESTAMP]", generated_at)
        prompt = prompt_template.replace("[PERSON_AND_CASE_DESCRIPTION]", case_text)
        request_body = {
            "model": args.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "top_p": 0.9,
            "top_k": 40,
            "seed": seed,
            "max_tokens": args.max_tokens,
            "stream": False,
        }
        write_json(run_dir / "request.json", request_body)

        started = time.perf_counter()
        print(f"run-{run_number}: generation started (seed={seed})", flush=True)
        run_result: dict[str, object] = {
            "run": run_number,
            "seed": seed,
            "generatedAtSupplied": generated_at,
        }
        try:
            request = urllib.request.Request(
                endpoint,
                data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
                raw_api_response = response.read().decode("utf-8")
            elapsed = round(time.perf_counter() - started, 3)
            api_response = json.loads(raw_api_response)
            write_json(run_dir / "response.api.json", api_response)
            content = api_response["choices"][0]["message"]["content"]
            (run_dir / "authoring-bundle.raw.txt").write_text(content, encoding="utf-8")
            parsed = False
            try:
                bundle = json.loads(content)
                write_json(run_dir / "authoring-bundle.json", bundle)
                parsed = True
            except json.JSONDecodeError as error:
                run_result["jsonError"] = {
                    "message": error.msg,
                    "line": error.lineno,
                    "column": error.colno,
                    "position": error.pos,
                }
            choice = api_response["choices"][0]
            run_result.update(
                {
                    "durationSeconds": elapsed,
                    "finishReason": choice.get("finish_reason"),
                    "usage": api_response.get("usage"),
                    "contentCharacters": len(content),
                    "jsonParsed": parsed,
                    "httpSucceeded": True,
                }
            )
            print(
                f"run-{run_number}: finished in {elapsed}s; "
                f"finish={choice.get('finish_reason')}; json={parsed}; chars={len(content)}",
                flush=True,
            )
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as error:
            elapsed = round(time.perf_counter() - started, 3)
            run_result.update(
                {
                    "durationSeconds": elapsed,
                    "httpSucceeded": False,
                    "errorType": type(error).__name__,
                    "error": str(error),
                }
            )
            print(f"run-{run_number}: failed after {elapsed}s: {error}", flush=True)

        runs = metadata["runs"]
        assert isinstance(runs, list)
        runs.append(run_result)
        write_json(args.output_dir / "generation-metadata.json", metadata)

    metadata["experimentFinishedAt"] = datetime.now(ZoneInfo("Europe/Rome")).isoformat(
        timespec="seconds"
    )
    write_json(args.output_dir / "generation-metadata.json", metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
