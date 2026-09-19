variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "Primary region for GKE, Cloud SQL, Pub/Sub, Cloud Run"
  type        = string
  default     = "us-central1"
}

variable "namespace" {
  description = "Kubernetes namespace for the sandbox app"
  type        = string
  default     = "autoops-sandbox"
}

variable "agent_image" {
  description = "Container image for the AutoOps agent (build + push via Cloud Build first)"
  type        = string
  default     = "gcr.io/PROJECT_ID/autoops-agent:latest"
}
