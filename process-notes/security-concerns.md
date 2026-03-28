# Security Concerns: Portfolio Build

This documents security issues introduced across the five portfolio repos, how to identify
each one, and what remediation looks like. Issues are grouped by severity tier.

---

## Critical

### 1. No secret scanning configured on any repo

**Where:** All five repos (brownm09, engineering-playbooks, aws-platform-demo,
incident-summarizer, ops-scripts)

**Risk:** A `.env` file, hardcoded token, or accidental credential commit would not be
caught before or after push. GitHub's default secret scanning does not push to branches
until explicitly enabled.

**Identify:**
```bash
# Check if GitHub Advanced Security / secret scanning is enabled
gh api repos/brownm09/{repo}/code-security-and-analysis

# Scan locally for secrets before pushing
pip install detect-secrets
detect-secrets scan --all-files > .secrets.baseline
detect-secrets audit .secrets.baseline
```

**Remediate:**
1. Enable GitHub secret scanning on each repo:
   Settings → Code security and analysis → Secret scanning → Enable
2. Add `detect-secrets` as a pre-commit hook so secrets are caught before they leave
   the workstation:
   ```yaml
   # .pre-commit-config.yaml
   repos:
     - repo: https://github.com/Yelp/detect-secrets
       rev: v1.4.0
       hooks:
         - id: detect-secrets
           args: ['--baseline', '.secrets.baseline']
   ```
3. Add `.env` and `*.pem` to `.gitignore` on any repo that doesn't already have them.

---

### 2. Admin API key has org-level blast radius

**Where:** `process-notes/usage_report.py`

**Risk:** The Anthropic admin key (`sk-ant-admin-*`) used by `usage_report.py` grants
read access to all usage data for your organization. If this key is committed, exposed
in logs, or stored alongside regular API keys in a shared `.env`, the blast radius is
the entire Anthropic org — not just one project.

**Identify:**
```bash
# Confirm the key used is an admin key, not a user key
grep -r "ANTHROPIC_ADMIN_KEY\|sk-ant-admin" . --include="*.py" --include="*.env*"
```

**Remediate:**
- Store admin keys in a separate secrets store from project API keys (1Password vault,
  AWS Secrets Manager, or a dedicated `.env.admin` file that is `.gitignore`d separately)
- Rotate admin keys on a schedule; they are not needed for production workloads
- Never pass admin keys as environment variables in CI/CD

---

## High

### 3. PII in incident payloads sent to the Anthropic API

**Where:** `incident_summarizer/summarizer.py`

**Risk:** `IncidentData` fields include `responders` (people's names), `description`
(free-text that may contain customer data), and the full `raw_data` from Jira or
PagerDuty. This data is sent to Anthropic's API. Depending on your data classification
policies and DPA with Anthropic, sending names and incident descriptions externally
may violate internal data handling requirements or customer contracts.

`summarizer.py` already strips `raw_data` when structured fields are present, but
`responders` and `description` pass through unconditionally.

**Identify:**
```bash
# Audit what fields are serialized before the API call
grep -n "model_dump\|incident_dict\|user_content" \
  incident_summarizer/summarizer.py
```

**Remediate:**
- Add a `redact` config flag that replaces `responders` with `["RESPONDER_1", ...]`
  and strips `description` before serialization
- Review Anthropic's data usage policy and your enterprise DPA to determine if
  zero-data-retention mode is required
- Consider running a local or on-prem model for incidents classified above a certain
  data sensitivity threshold

---

### 4. OIDC trust policy scope in GitHub Actions

**Where:** `aws-platform-demo/.github/workflows/ci.yml`

**Risk:** The OIDC trust policy for the IAM role used by GitHub Actions needs to be
scoped to the specific repo and ideally to specific branches or environments. An overly
broad trust policy (e.g., `StringLike` on `token.actions.githubusercontent.com:sub`
matching `repo:brownm09/*`) would allow any repo in your GitHub account to assume
the deployment role.

The workflow references the role but the trust policy configuration is out-of-band —
it lives in the AWS account, not the repo. If it was set up permissively, any repo
you create could deploy to the target account.

**Identify:**
```bash
# Pull the current trust policy for your OIDC role
aws iam get-role --role-name <github-actions-role-name> \
  --query 'Role.AssumeRolePolicyDocument'
```

Look for the `token.actions.githubusercontent.com:sub` condition. It should be:
```json
"StringEquals": {
  "token.actions.githubusercontent.com:sub":
    "repo:brownm09/aws-platform-demo:ref:refs/heads/main"
}
```
Not `StringLike` with a wildcard.

**Remediate:**
- Use `StringEquals` (not `StringLike`) on the `sub` claim
- Scope to the specific repo and branch or environment:
  `repo:brownm09/aws-platform-demo:environment:prod`
- Add an explicit `StringEquals` on the `aud` claim:
  `token.actions.githubusercontent.com:aud = sts.amazonaws.com`

---

### 5. GitHub Actions workflow pins actions by tag, not SHA

**Where:** `aws-platform-demo/.github/workflows/ci.yml`

**Risk:** Actions pinned by tag (e.g., `aws-actions/configure-aws-credentials@v4`)
can be silently updated by the action author. A compromised or malicious update would
run automatically on your next workflow trigger. This is a supply chain attack vector.

**Identify:**
```bash
grep -n "uses:" .github/workflows/ci.yml | grep -v "@[a-f0-9]\{40\}"
```
Any result that doesn't end in a 40-character SHA is unpinned.

**Remediate:**
Pin each action to the commit SHA of the version you trust:
```yaml
# Before
- uses: aws-actions/configure-aws-credentials@v4

# After (get the SHA from the action's release tags on GitHub)
- uses: aws-actions/configure-aws-credentials@e3dd6a429d7300a6a4c196c26e069d42e0343502  # v4.0.2
```

Tools that automate this: `pinact` (GitHub CLI extension), Dependabot with
`update-github-actions` groups.

---

### 6. Terraform state backend not configured; no remote state encryption

**Where:** `aws-platform-demo/environments/prod/`

**Risk:** The demo uses local state (no `backend` block). In a real deployment,
Terraform state contains resource IDs, ARNs, and any outputs that were not explicitly
marked `sensitive`. Even with `manage_master_user_password = true` on Aurora, other
module outputs (VPC IDs, security group IDs, ECS cluster ARNs) could assist an
attacker in mapping your infrastructure.

**Identify:**
```bash
# Check for a backend block
grep -r "backend" environments/prod/ --include="*.tf"

# Check state for sensitive-looking values if local state exists
jq '.resources[].instances[].attributes | to_entries[] | select(.value | type == "string") | select(.value | test("^[A-Za-z0-9+/]{32,}$"))' terraform.tfstate
```

**Remediate:**
- Use an S3 backend with DynamoDB state locking:
  ```hcl
  terraform {
    backend "s3" {
      bucket         = "your-tf-state-bucket"
      key            = "prod/terraform.tfstate"
      region         = "us-east-1"
      encrypt        = true
      dynamodb_table = "terraform-lock"
    }
  }
  ```
- Enable S3 server-side encryption (SSE-KMS) on the state bucket
- Block public access on the state bucket
- Enable versioning for rollback capability
- Mark module outputs that are resource IDs as `sensitive = true` where appropriate

---

## Medium

### 7. File adapter: no path traversal protection

**Where:** `incident_summarizer/inputs/file.py:36-38`

**Risk:** The `file_path` config value is passed directly to `Path(file_path).read_text()`.
If this adapter is called from a web service or any context where `file_path` is
user-controlled (not just the CLI), an attacker could read arbitrary files on the
server (`../../etc/passwd`, secrets files, etc.).

**Identify:**
```python
# Current code (file.py:35-38)
path = Path(file_path)
if not path.exists():
    raise ValueError(f"File not found: {file_path}")
content = path.read_text(encoding="utf-8")
```
No resolution to a known-safe base directory.

**Remediate:**
Add a configurable base directory and resolve against it:
```python
base_dir = Path(self.config.get("base_dir", ".")).resolve()
path = (base_dir / file_path).resolve()
if not str(path).startswith(str(base_dir)):
    raise ValueError(f"Path traversal rejected: {file_path}")
```
In a CLI-only context, this is low risk — the user running the CLI already has
filesystem access. It becomes high risk if the adapter is wrapped in an HTTP endpoint.

---

### 8. Jira webhook dict merge can allow field override

**Where:** `incident_summarizer/inputs/file.py:68`

**Risk:** The Jira webhook payload handling merges `data["issue"]["fields"]` and then
the outer `data` dict onto each other:
```python
data = {**data["issue"]["fields"], "id": data["issue"]["key"], **data}
```
The outer `data` unpacking comes last, so outer keys override inner `fields` keys.
A crafted webhook payload with top-level keys matching field names (`summary`, `status`,
etc.) would silently override the extracted field values.

In a CLI context this only affects the operator. If this tool processes webhook payloads
from a public endpoint, a malicious sender could manipulate the incident data Claude sees.

**Remediate:**
Make the merge order explicit and prefer inner fields:
```python
outer_safe = {k: v for k, v in data.items() if k not in data["issue"]["fields"]}
data = {"id": data["issue"]["key"], **data["issue"]["fields"], **outer_safe}
```
Or extract only the fields you need explicitly rather than using a broad merge.

---

### 9. Engineering playbooks expose internal topology in a public repo

**Where:** `engineering-playbooks/` — all documents

**Risk:** The playbooks reference specific tools, team structures, rotation cadences,
incident counts, and in some cases vendor names (Jeli, Jira, Heroku, PagerDuty). This
is intentional for portfolio credibility, but it also describes your organization's
security response procedures, on-call structure, and toolchain to anyone who reads it.

This is a tradeoff, not an absolute vulnerability. The concern is that a public
rundown of incident response procedures, tool combinations, and team structure reduces
the effort required for a targeted social engineering or phishing attack.

**Remediate (if the tradeoff is unacceptable):**
- Move the repo to private and share specific docs via links with token-based access
- Redact specific tool names and vendor identifiers from public versions
- Replace person-specific rotation details with generic role names

The current state is a reasonable portfolio tradeoff. Document the decision so
future readers understand it was deliberate.

---

### 10. No dependency vulnerability scanning

**Where:** `incident-summarizer/pyproject.toml`, `ops-scripts/pyproject.toml`,
`aws-platform-demo/.github/workflows/ci.yml`

**Risk:** `anthropic`, `boto3`, `requests`, `click`, and `pydantic` are pinned
with `>=` minimums, not exact versions. A vulnerability in any of these packages
would not trigger an alert.

**Identify:**
```bash
pip install pip-audit
pip-audit -r requirements.txt

# For Terraform providers
terraform providers lock  # then audit the .terraform.lock.hcl file
```

**Remediate:**
Enable Dependabot on each repo:
```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
```
For Terraform repos, add:
```yaml
  - package-ecosystem: terraform
    directory: /environments/prod
    schedule:
      interval: weekly
```

---

### 11. IAM ECS task role allows `logs:*` across all log groups

**Where:** `aws-platform-demo/modules/iam/main.tf`

**Risk:** The task role grants `logs:CreateLogGroup`, `logs:CreateLogStream`, and
`logs:PutLogEvents` without a `Resource` condition scoped to the application's log
group. A compromised container could write to any log group in the account, potentially
contaminating audit trails or overwriting security-relevant logs.

**Identify:**
```bash
grep -A 20 "logs" modules/iam/main.tf
```

**Remediate:**
Scope the log actions to the specific log group ARN:
```hcl
resource "aws_iam_role_policy" "task_logs" {
  role = aws_iam_role.ecs_task.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = "${aws_cloudwatch_log_group.app.arn}:*"
    }]
  })
}
```
`logs:CreateLogGroup` can be removed entirely if the log group is pre-created by
Terraform (which it is in the demo).

---

## Low

### 12. Slack webhook URL exposed in process logs

**Where:** `incident_summarizer/outputs/slack.py`

**Risk:** If Python logging is set to DEBUG level, the `requests` library may log the
full webhook URL (which acts as a bearer token). The URL itself is the auth mechanism
for Slack webhooks — anyone with it can post to the channel.

**Identify:**
```bash
grep -r "logging.basicConfig\|log_level.*DEBUG" incident_summarizer/
```

**Remediate:**
- Rotate webhook URLs if they appear in logs or are passed via command-line arguments
  (command history is visible to other processes)
- Pass via environment variable only (current implementation does this)
- Set `PYTHONWARNINGS=default` and avoid DEBUG-level logging in production

---

### 13. `raw_data` field stores full API responses in IncidentSummary

**Where:** `incident_summarizer/models.py:34`, `incident_summarizer/inputs/pagerduty.py:97`

**Risk:** `PagerDutyAdapter` sets `raw_data=incident` — the full API response object.
This propagates into `IncidentSummary.raw_data` (via `raw_data` on `IncidentData`),
which is then written to JSON output files, SNS messages, and S3 objects. The full
PagerDuty incident object can contain webhook URLs, integration keys, and internal
service metadata.

**Identify:**
```bash
# Check if raw_data is included in serialized output
python3 -c "
from incident_summarizer.models import IncidentSummary, AffectedServices, CostEstimate
print([f for f in IncidentSummary.model_fields])
"
```

**Remediate:**
- Set `exclude={"raw_data"}` in `model_dump()` calls in output adapters, or
- Strip `raw_data` in `summarizer.py` before it reaches the summary model, or
- Mark the field `exclude=True` in the Pydantic model definition if you never
  need it in output

---

## Identification and Remediation Checklist

Run this before treating any of these repos as production-ready:

```
[ ] Enable GitHub secret scanning on all repos
[ ] Add detect-secrets pre-commit hook to workstation
[ ] Verify OIDC trust policy uses StringEquals + repo-scoped sub claim
[ ] Pin GitHub Actions to SHAs; add Dependabot for auto-updates
[ ] Configure S3 + DynamoDB backend for Terraform state
[ ] Enable Dependabot on all Python repos
[ ] Review Anthropic DPA for data classification requirements
[ ] Scope ECS task role log actions to specific log group ARN
[ ] Add redact option to incident-summarizer for PII fields
[ ] Strip or exclude raw_data from output serialization
[ ] Rotate any credentials that appeared in command-line args or logs
```

---

## Tools Referenced

| Tool | Purpose | Install |
|---|---|---|
| `detect-secrets` | Pre-commit secret scanning | `pip install detect-secrets` |
| `pip-audit` | Python dependency CVE scanning | `pip install pip-audit` |
| `checkov` | Terraform/IaC static analysis | `pip install checkov` |
| `pinact` | Pin GitHub Actions to SHAs | `gh extension install kfukue/pinact` |
| Dependabot | Automated dependency PRs | `.github/dependabot.yml` |
| GitHub secret scanning | Post-push secret detection | Settings → Code security |
| AWS IAM Access Analyzer | Detect overly permissive policies | AWS console or CLI |
