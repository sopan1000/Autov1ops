# The agent itself - the one mandatory-per-the-rules Cloud Run deployment.
resource "google_cloud_run_v2_service" "agent" {
  name     = "autoops-agent"
  location = var.region

  # Pub/Sub push tokens are minted for this fixed audience. Using the
  # service's own URL here would be a self-reference Terraform rejects.
  custom_audiences = [var.pubsub_audience]

  template {
    service_account = google_service_account.agent.email
    max_instance_request_concurrency = 20
    scaling {
      min_instance_count = 1
      max_instance_count = 5
    }

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
        name  = "GEMINI_MODEL"
        value = var.gemini_model
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
      env {
        name  = "GKE_CLUSTER"
        value = var.gke_cluster_name
      }
      env {
        name  = "GKE_LOCATION"
        value = var.region
      }
      env {
        name  = "PUBSUB_AUDIENCE"
        value = var.pubsub_audience
      }
      env {
        name = "AUTOOPS_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.api_key.id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}


# Demo day only: lets judges open the dashboard (served at /ui) without a
# Google login. Leave false for anything real; put the UI behind IAP instead.
resource "google_cloud_run_v2_service_iam_member" "public_demo" {
  count    = var.public_demo ? 1 : 0
  name     = google_cloud_run_v2_service.agent.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
