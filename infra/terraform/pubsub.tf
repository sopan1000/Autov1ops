resource "google_pubsub_topic" "incidents" {
  name = "autoops-incidents"
}

resource "google_service_account" "pubsub_push" {
  account_id   = "autoops-pubsub-push"
  display_name = "AutoOps Pub/Sub push identity"
}

resource "google_cloud_run_v2_service_iam_member" "pubsub_invoker" {
  name     = google_cloud_run_v2_service.agent.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pubsub_push.email}"
}

resource "google_pubsub_subscription" "to_agent" {
  name  = "autoops-incidents-to-agent"
  topic = google_pubsub_topic.incidents.name

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.agent.uri}/events/pubsub"
    oidc_token {
      service_account_email = google_service_account.pubsub_push.email
      audience              = var.pubsub_audience
    }
  }

  ack_deadline_seconds = 300
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}
