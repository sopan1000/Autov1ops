# Deploying AutoOps

Two paths. **Do the fast path first**: it satisfies every mandatory
submission rule (Gemini + an agentic platform + deployed on Cloud Run) in
under an hour. The full path is a stretch goal.

| | Fast path | Full path |
|---|---|---|
| Agent on Cloud Run | ✅ | ✅ |
| Gemini via ADK on Vertex AI | ✅ | ✅ |
| Durable state (Firestore) | ✅ | ✅ |
| Dashboard at `<service-url>/ui` | ✅ | ✅ |
| Evidence source | fixture incidents | live GKE cluster, Cloud Logging, Monitoring |
| Fixes applied to | nothing (simulated) | the real sandbox cluster |

---

## Step 0: Check Gemini works (10 minutes)

Do this before deploying anything. It catches model, quota and permission
problems while they're cheap to fix.

```bash
pip install -r agent/requirements.txt

# Option A, quickest: an AI Studio key (https://aistudio.google.com/apikey)
GOOGLE_API_KEY=your-key python scripts/gemini_smoke_test.py

# Option B: Vertex AI with your own login
gcloud auth application-default login
GCP_PROJECT=your-project GCP_LOCATION=us-central1 python scripts/gemini_smoke_test.py
```

You want `5/5 scenarios passed`. Each incident should take roughly 4 Gemini
requests (the output shows the count). To save quota while iterating, run
just the scenarios you care about: `python scripts/gemini_smoke_test.py cert_expiry`. For each scenario it prints the root cause,
the chosen fix, Gemini's justification and which tools the investigator called.

- **`fell back to offline engine: ... 404 NOT_FOUND ... model`**: that model
  isn't available to your account or region. The error message usually names
  the replacement; set `GEMINI_MODEL` to it (or to one listed in AI Studio /
  Vertex AI Studio). On Vertex AI, also try `GCP_LOCATION=global`.
- **`429 RESOURCE_EXHAUSTED`**: free-tier quota. Check your limits at
  https://aistudio.google.com/rate-limit. For a per-minute limit, set
  `GEMINI_RPM` to it (AutoOps then spaces requests out); for the daily limit,
  wait for the reset at midnight Pacific time. **For demo day and judging,
  don't rely on the free tier:** enable billing on the key's project (each
  incident costs a tiny fraction of a cent) or use Vertex AI on Cloud Run with
  your hackathon credits, which uses the project's paid quota.
- **Incidents are slow**: they should take well under a minute. Keep
  `GEMINI_THINKING_LEVEL=low` (the default). If an error mentions thinking,
  set it to an empty string.
- **`PermissionDenied`**: enable the Vertex AI API on the project and make sure
  your account has *Vertex AI User*.
- **A scenario picks a different fix**: read the justification. If the
  reasoning is sound, update `EXPECTED_FIX` in the script; if not, tune the
  prompts in `agent/adk_pipeline.py`. You can also try a stronger diagnosis model:
  `GEMINI_DIAGNOSIS_MODEL=<a Pro model listed in AI Studio>`.

## Fast path: Cloud Run + Gemini + Firestore

```bash
export PROJECT=your-project-id REGION=us-central1
gcloud config set project $PROJECT

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com aiplatform.googleapis.com firestore.googleapis.com

# Firestore for incidents/runbooks (skip if the project already has one)
gcloud firestore databases create --location=$REGION

# Let the Cloud Run runtime identity call Gemini and use Firestore
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
SA=$PROJECT_NUMBER-compute@developer.gserviceaccount.com
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/aiplatform.user
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/datastore.user

# Build from source and deploy (run from the repo root)
gcloud run deploy autoops-agent --source . --region $REGION \
  --allow-unauthenticated --min-instances 1 --max-instances 2 --timeout 300 \
  --set-env-vars "USE_REAL_GEMINI=true,GCP_PROJECT=$PROJECT,GCP_LOCATION=$REGION,GEMINI_MODEL=gemini-3.8-flash,MOCK_TOOLS=true,STORE_BACKEND=firestore"
```

Open the printed service URL. It redirects to the dashboard at `/ui`, and the
header should show **AI: gemini-… via ADK** in green. Click **cert expiry**
and you should get a specific diagnosis with `rollback_api`, not an escalation.

Redeploy after code changes with the same `gcloud run deploy` command, or
`gcloud builds submit --config cloudbuild.yaml .` (keeps the existing env vars).

**About `--allow-unauthenticated`:** it lets judges open the URL without a
Google login. That's fine here because the fast path never touches real
infrastructure, but anyone with the URL can trigger Gemini calls. Keep
`--max-instances` low, and delete the service or remove public access after
judging (`gcloud run services remove-iam-policy-binding autoops-agent
--region $REGION --member=allUsers --role=roles/run.invoker`). Don't set
`AUTOOPS_API_KEY` on a public demo: the dashboard has no way to send it.

## Full path (stretch): live GKE cluster

Only start this after the fast path works and the video is recorded.

1. `cd infra/terraform && terraform init && terraform validate`.
   Terraform couldn't be run while these files were written, so validate first.
2. Terraform creates the `autoops-api-key` secret but not its value, and Cloud Run
   won't start without one. Create the secret first, add a value, then apply everything:
   ```bash
   terraform apply -var="project_id=$PROJECT" -target=google_secret_manager_secret.api_key
   printf 'YOUR-KEY' | gcloud secrets versions add autoops-api-key --data-file=-
   terraform apply -var="project_id=$PROJECT" -var="agent_image=<image from the fast path>"
   ```
   The fast path already created the Cloud Run service and the Firestore
   database, so import them instead of letting Terraform fail on "already exists":
   `terraform import google_cloud_run_v2_service.agent projects/$PROJECT/locations/$REGION/services/autoops-agent`
   and `terraform import google_firestore_database.default "projects/$PROJECT/databases/(default)"`.
3. Build and push `sandbox/api` and `sandbox/worker` images, update the image
   names in `sandbox/k8s/*.yaml`, then `kubectl apply -f sandbox/k8s/`.
4. Edit `sandbox/k8s/rbac.yaml` with the agent's service-account email and apply it.
5. Set `MOCK_TOOLS=false` on the service, plus `GITHUB_REPO` / `GITHUB_TOKEN`
   for deploy history.
6. Create a Cloud Monitoring alert policy whose notification channel publishes
   to the `autoops-incidents` topic, with a `scenario` attribute on the message.
7. Run a chaos script against the live cluster (for example `sandbox/chaos/bad_deploy.sh`)
   and watch the real rollback happen.

Note: with `MOCK_TOOLS=false` the investigator reads live logs and events,
so the chaos scripts' `scenario` names only label the incident; the evidence
is whatever the cluster actually produced.
