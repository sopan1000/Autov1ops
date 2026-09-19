# The agent itself - the one mandatory-per-the-rules Cloud Run deployment.
resource "google_cloud_run_v2_service" "agent" {
  name     = "autoops-agent"
  location = var.region

  template {
    service_account = google_service_account.agent.email

    containers {
      image = var.agent_image
      env {
        name  = "MOCK_TOOLS"
        value = "false"
      }
      env {
        name  = "STORE_BACKEND"
        value = "firestore"
      }
      env {
        name  = "USE_REAL_GEMINI"
        value = "true"
      }
      env {
        name  = "GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GCP_LOCATION"
        value = var.region
      }
      env {
        name  = "K8S_NAMESPACE"
        value = var.namespace
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service_iam_member" "pubsub_invoker" {
  name     = google_cloud_run_v2_service.agent.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"  # tighten to a dedicated Pub/Sub push service account before real prod use
}
