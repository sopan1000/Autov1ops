output "agent_url" {
  value = google_cloud_run_v2_service.agent.uri
}

output "gke_cluster_name" {
  value = google_container_cluster.sandbox.name
}

output "cloudsql_connection_name" {
  value = google_sql_database_instance.primary.connection_name
}
