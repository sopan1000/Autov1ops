# Deliberately narrow: the agent's service account can read logs/metrics
# project-wide, but its write access to the cluster is scoped to the
# autoops-sandbox namespace only via RBAC (applied separately with kubectl,
# see sandbox/k8s/ — Terraform provisions the identity, not the RBAC
# RoleBinding, since that needs the cluster to exist first).
resource "google_service_account" "agent" {
  account_id   = "autoops-agent"
  display_name = "AutoOps agent runtime identity"
}

resource "google_project_iam_member" "agent_logging_viewer" {
  project = var.project_id
  role    = "roles/logging.viewer"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_project_iam_member" "agent_monitoring_viewer" {
  project = var.project_id
  role    = "roles/monitoring.viewer"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_project_iam_member" "agent_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_project_iam_member" "agent_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

# Kubernetes-side write access is granted narrowly to this namespace only,
# via a RoleBinding (not a ClusterRoleBinding) applied post-cluster-creation:
#   kubectl create rolebinding autoops-agent-editor \
#     --role=edit --serviceaccount=autoops-sandbox:autoops-agent \
#     -n autoops-sandbox
# with Workload Identity binding the GSA above to that KSA.

resource "google_project_iam_member" "agent_container_viewer" {
  project = var.project_id
  role    = "roles/container.viewer"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_secret_manager_secret_iam_member" "agent_api_key" {
  project   = var.project_id
  secret_id = var.api_key_secret_name
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent.email}"
}
