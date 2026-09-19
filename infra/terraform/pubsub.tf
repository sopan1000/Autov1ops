# The doorbell: a Cloud Monitoring alert policy publishes here, and a push
# subscription forwards straight to the agent's /alerts endpoint on Cloud
# Run. Wire the alert policy itself in the Cloud Console or via
# google_monitoring_alert_policy once you've picked real thresholds against
# the sandbox app's traffic pattern.
resource "google_pubsub_topic" "incidents" {
  name = "autoops-incidents"
}

resource "google_pubsub_subscription" "to_agent" {
  name  = "autoops-incidents-to-agent"
  topic = google_pubsub_topic.incidents.name

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.agent.uri}/alerts"
  }

  ack_deadline_seconds = 30
}
