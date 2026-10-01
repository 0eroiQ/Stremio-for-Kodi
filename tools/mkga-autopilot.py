#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.getenv("MKGA_URL", "https://mkga.tv").rstrip("/")
SERVICE_TOKEN = os.environ["MKGA_LAB_AUTOPILOT_TOKEN"]
REPO = Path(__file__).resolve().parents[1]
ACTIVE_JOB = None

def api(path, method="GET", payload=None, token=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "authorization": "Bearer " + (token or SERVICE_TOKEN),
            "content-type": "application/json",
            "user-agent": "mkga-autopilot/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.load(response)
def run(args, *, check=True, env=None, timeout=900):
    result = subprocess.run(
        args, cwd=REPO, text=True, capture_output=True, env=env, timeout=timeout
    )
    if check and result.returncode:
        raise RuntimeError(
            f"{' '.join(args)} failed ({result.returncode})\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}"
        )
    return result

def git(*args, check=True):
    return run(["git", *args], check=check)

def task_text(data):
    task = data["task"]
    messages = data.get("messages", [])
    context = "\n\n".join(
        f"{m.get('author_label','MKGA')}: {m.get('body','')}"
        for m in messages[-8:]
    )
    plan = task.get("plan") or {}
    return (
        f"TITLE: {task['title']}\n"
        f"DIFFICULTY: {plan.get('label','AUTO')}\n"
        f"TESTING: {plan.get('testing','auto')}\n\n"
        f"{context}"
    )

def repo_context(statement):
    files = git("ls-files").stdout.splitlines()[:500]
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", statement)]
    stop = {"this","that","with","from","have","will","when","then","task","kodi","stremio","issue"}
    words = list(dict.fromkeys(w for w in words if w not in stop))[:10]
    matches = ""
    if words:
        pattern = "|".join(re.escape(w) for w in words)
        found = run(["git", "grep", "-n", "-i", "-E", pattern], check=False, timeout=60)
        matches = "\n".join(found.stdout.splitlines()[:140])
    return "REPOSITORY FILES:\n" + "\n".join(files) + "\n\nSEARCH MATCHES:\n" + matches

def ai_chat(ai_token, messages, model="mkga-free", max_tokens=1400):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    try:
        return api("/api/lab/ai/v1/chat/completions", "POST", payload, ai_token)["choices"][0]["message"]["content"]
    except Exception:
        if model != "mkga-free":
            payload["model"] = "mkga-free"
            return api("/api/lab/ai/v1/chat/completions", "POST", payload, ai_token)["choices"][0]["message"]["content"]
        raise

def update_agent(task_id, agent, status, verdict=None, summary=None, provider=None):
    api(
        f"/api/lab/agent/tasks/{task_id}/agents/{agent['id']}",
        "POST",
        {"status": status, "verdict": verdict, "summary": summary, "provider": provider},
    )

def analyze(task_id, agent, statement, context, ai_token):
    update_agent(task_id, agent, "working", provider="cloudflare-free")
    role = agent["role"]
    prompt = (
        "You are the MKGA Autopilot " + role + " reviewer. "
        "Analyze only; do not write code. Give a concrete root-cause/implementation recommendation. "
        "Call out uncertainty and likely regressions. Be concise.\n\n"
        + statement + "\n\n" + context
    )
    answer = ai_chat(ai_token, [{"role": "user", "content": prompt}], "mkga-free", 1200)
    update_agent(task_id, agent, "completed", "ANALYZED", answer[:8000], "cloudflare-glm")
    return f"[{role}]\n{answer}"

def _extract_command(answer):
    fences = re.findall(r"```(?:bash|sh|shell|mswea_bash_command)?\\s*\\n(.*?)```", answer, re.S | re.I)
    if fences:
        return fences[-1].strip()
    m = re.search(r"<command>(.*?)</command>", answer, re.S | re.I)
    return m.group(1).strip() if m else ""

def _safe_coder_command(command):
    blocked = [
        r"\\bgit\\s+push\\b", r"\\bgh\\s+pr\\b", r"\\bgh\\s+release\\b",
        r"\\bsudo\\b", r"\\brm\\s+-rf\\s+/", r"\\bcurl\\b.*\\|\\s*(?:sh|bash)",
        r"\\bwget\\b.*\\|\\s*(?:sh|bash)", r"MKGA_LAB_", r"GITHUB_TOKEN", r"GH_TOKEN",
    ]
    return not any(re.search(p, command, re.I | re.S) for p in blocked)

def run_coder(statement, analyses, ai_token, feedback=""):
    system = (
        "You are MKGA Autopilot's implementation worker inside an ephemeral GitHub Actions checkout. "
        "Your job is to inspect, edit, and test the repository, not merely explain. "
        "On EVERY turn return exactly one executable shell command inside a ```bash fenced block. "
        "Use focused commands: read relevant files, then edit with python/sed/cat, then test. "
        "Do not run git push, gh, releases, sudo, curl|sh, wget|sh, or read environment secrets. "
        "You have at most 8 turns. By turn 4 you should make a justified edit unless evidence proves no code change is appropriate. "
        "When finished, the only command must be: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    )
    task = (
        statement + "\\n\\nINDEPENDENT ANALYSIS:\\n" + "\\n\\n".join(analyses)
        + ("\\n\\nREVIEW/TEST FEEDBACK TO FIX:\\n" + feedback if feedback else "")
        + "\\n\\nImplement the smallest safe fix now."
    )
    messages = [{"role":"system","content":system},{"role":"user","content":task}]
    transcript=[]
    clean_env={k:v for k,v in os.environ.items() if not (k.startswith('MKGA_') or k in {'GH_TOKEN','GITHUB_TOKEN','OPENAI_API_KEY'})}
    for step in range(1,9):
        answer=ai_chat(ai_token,messages,"mkga-free-coder",1000)
        command=_extract_command(answer)
        transcript.append(f"STEP {step} AI:\\n{answer}")
        if not command:
            messages.append({"role":"assistant","content":answer})
            messages.append({"role":"user","content":"FORMAT ERROR: return exactly one executable command in a ```bash fenced block. Do not explain outside the block."})
            continue
        if command.strip()=="echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT":
            return subprocess.CompletedProcess(["mkga-free-coder"],0,"\\n\\n".join(transcript),"")
        if not _safe_coder_command(command):
            messages.append({"role":"assistant","content":answer})
            messages.append({"role":"user","content":"That command is blocked by MKGA safety policy. Choose a safe local repository command instead."})
            continue
        result=run(["bash","-lc",command],check=False,env=clean_env,timeout=120)
        observation=(result.stdout+result.stderr)[-7000:]
        transcript.append(f"STEP {step} COMMAND:\\n{command}\\nRESULT {result.returncode}:\\n{observation}")
        messages.append({"role":"assistant","content":answer})
        messages.append({"role":"user","content":f"Command exit code: {result.returncode}\\nOutput:\\n{observation}\\nContinue. Remember: exactly one ```bash command, and finish only after the fix is implemented and checked."})
    return subprocess.CompletedProcess(["mkga-free-coder"],1,"\\n\\n".join(transcript),"free coder reached the 8-step limit")

def validate():
    tests = run(["python3", "-m", "unittest", "discover", "-s", "tests"], check=False, timeout=900)
    build = run(["python3", "tools/build-stremio-addon.py", "--output", "dist"], check=False, timeout=300)
    ok = tests.returncode == 0 and build.returncode == 0
    log = (
        "UNIT TESTS\n" + tests.stdout[-6000:] + tests.stderr[-3000:]
        + "\n\nBUILD\n" + build.stdout[-3000:] + build.stderr[-2000:]
    )
    return ok, log
def review(task_id, reviewers, statement, diff, test_log, ai_token):
    failures = []
    for index, agent in enumerate(reviewers):
        update_agent(task_id, agent, "working", provider="cloudflare-free")
        prompt = (
            f"You are an independent {agent['role']} for MKGA Autopilot.\n"
            "Review the proposed patch against the task and test results. "
            "Start your answer with exactly VERDICT: PASS or VERDICT: FAIL. "
            "FAIL only for a concrete correctness, regression, security, or missing-test problem.\n\n"
            + statement + "\n\nDIFF:\n" + diff[:42000] + "\n\nTESTS:\n" + test_log[-9000:]
        )
        model = "mkga-free-review" if index % 2 == 0 else "mkga-free"
        answer = ai_chat(ai_token, [{"role": "user", "content": prompt}], model, 1200)
        passed = answer.lstrip().upper().startswith("VERDICT: PASS")
        update_agent(
            task_id, agent, "pass" if passed else "fail",
            "PASS" if passed else "FAIL", answer[:8000],
            "cloudflare-gemma" if model == "mkga-free-review" else "cloudflare-glm",
        )
        if not passed:
            failures.append(f"[{agent['role']}] {answer}")
    return failures

def lab_reply(task_id, job_id, body, status):
    return api(
        f"/api/lab/agent/tasks/{task_id}/reply",
        "POST",
        {"jobId": job_id, "body": body[:12000], "status": status},
    )

def main():
    global ACTIVE_JOB
    jobs = api("/api/lab/agent/jobs?provider=auto-free").get("jobs", [])
    if not jobs:
        print("No MKGA free-autopilot jobs.")
        return 0
    job = jobs[0]
    ACTIVE_JOB = job
    task_id, job_id = job["task_id"], job["id"]
    api(f"/api/lab/agent/jobs/{job_id}/claim", "POST", {})
    data = api(f"/api/lab/agent/tasks/{task_id}")
    token_data = api(f"/api/lab/agent/jobs/{job_id}/ai-token", "POST", {})
    ai_token = token_data["token"]
    statement = task_text(data)
    plan = data["task"].get("plan") or {}
    agents = data.get("agents", [])
    analysis_agents = [a for a in agents if a["phase"] == "analysis"]
    coder_agents = [a for a in agents if a["phase"] == "implementation"]
    reviewers = [a for a in agents if a["phase"] == "review"]

    lab_reply(task_id, job_id, f"Autopilot started · {plan.get('label','AUTO')} · FREE ONLY · $0 paid fallback.", "working")
    context = repo_context(statement)
    analyses = []
    for a in analysis_agents:
        if a.get("status") == "completed" and a.get("summary"):
            analyses.append(f"[{a['role']}]\n{a['summary']}")
        else:
            analyses.append(analyze(task_id, a, statement, context, ai_token))

    branch = "ai/mkga-" + re.sub(r"[^a-zA-Z0-9]", "", task_id)[:8].lower() + "-" + re.sub(r"[^a-zA-Z0-9]", "", job_id)[:6].lower()
    git("switch", "-c", branch)
    if coder_agents:
        update_agent(task_id, coder_agents[0], "working", provider="cloudflare-glm")

    max_attempts = max(1, min(3, int(plan.get("maxAttempts", 2))))
    feedback = ""
    final_test_log = ""
    review_failures = []
    for attempt in range(1, max_attempts + 1):
        coder = run_coder(statement, analyses, ai_token, feedback)
        print(f"Coder attempt {attempt} exit={coder.returncode}")
        if coder.stdout:
            print("CODER STDOUT (tail):\n" + coder.stdout[-6000:])
        if coder.stderr:
            print("CODER STDERR (tail):\n" + coder.stderr[-6000:], file=sys.stderr)
        if coder.returncode != 0:
            raise RuntimeError("coding agent process failed: " + (coder.stdout + "\n" + coder.stderr)[-3000:])
        diff = git("diff", "--", ".", check=False).stdout
        if not diff.strip():
            feedback = "No code changes were produced. Inspect the repository again and implement the requested fix."
            if attempt < max_attempts:
                continue
            raise RuntimeError("coder produced no changes")
        tests_ok, final_test_log = validate()
        if not tests_ok:
            feedback = "Tests/build failed. Fix these failures:\n" + final_test_log[-9000:]
            if attempt < max_attempts:
                continue
            raise RuntimeError("tests/build still failing after retries")
        review_failures = review(task_id, reviewers, statement, diff, final_test_log, ai_token)
        if not review_failures:
            break
        feedback = "\n\n".join(review_failures)
        if attempt == max_attempts:
            raise RuntimeError("independent review did not pass")
        for a in reviewers:
            update_agent(task_id, a, "waiting", summary="Waiting for revised patch.")
    if coder_agents:
        update_agent(task_id, coder_agents[0], "completed", "PASS", "Implementation completed and validation passed.", "cloudflare-glm")

    git("config", "user.name", "MKGA Autopilot")
    git("config", "user.email", "autopilot@mkga.tv")
    git("add", "-A")
    git("commit", "-m", f"fix: MKGA Lab {data['task']['title'][:70]}")
    sha = git("rev-parse", "HEAD").stdout.strip()

    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not gh_token:
        raise RuntimeError("GitHub token unavailable for PR creation")
    push_env = os.environ.copy()
    push_env["GH_TOKEN"] = gh_token
    run(["gh", "auth", "setup-git"], env=push_env)
    git("push", "-u", "origin", branch)

    body = (
        "Automated MKGA Lab proposal.\n\n"
        f"Task: {data['task']['title']}\n"
        f"Difficulty: {plan.get('label','AUTO')}\n"
        "AI policy: FREE ONLY; paid fallback disabled.\n"
        "Validation: unit tests + addon build passed.\n\n"
        "This PR is never auto-merged; owner review is required."
    )
    pr = run(
        ["gh", "pr", "create", "--base", "main", "--head", branch,
         "--title", f"[MKGA Autopilot] {data['task']['title'][:90]}", "--body", body],
        env=push_env,
    ).stdout.strip()
    api(
        f"/api/lab/agent/tasks/{task_id}/result",
        "POST",
        {
            "branch": branch,
            "commitSha": sha,
            "testStatus": "passed",
            "reviewStatus": "passed",
            "status": "proposal_ready",
            "prUrl": pr,
        },
    )
    lab_reply(
        task_id, job_id,
        f"FREE Autopilot finished.\n\n✓ Code changed\n✓ Tests passed\n✓ Independent review passed\n✓ Branch: {branch}\n✓ Commit: {sha[:12]}\n✓ PR: {pr}\n\nMerge remains manual.",
        "proposal_ready",
    )
    print(pr)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"MKGA Autopilot failed: {exc}", file=sys.stderr)
        try:
            if ACTIVE_JOB:
                lab_reply(ACTIVE_JOB["task_id"], ACTIVE_JOB["id"], f"Autopilot blocked: {exc}", "blocked")
        except Exception:
            pass
        raise
