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

variable "gke_cluster_name" {
  description = "GKE cluster name used by the AutoOps agent"
  type        = string
  default     = "autoops-sandbox"
}

variable "api_key_secret_name" {
  description = "Existing Secret Manager secret containing the dashboard/API bearer token"
  type        = string
  default     = "autoops-api-key"
}

variable "pubsub_audience" {
  description = "Fixed OIDC audience for Pub/Sub push tokens (also set as a Cloud Run custom audience)"
  type        = string
  default     = "autoops-pubsub-push"
}

variable "gemini_model" {
  description = "Gemini model used by the ADK agents (pick the newest one available in Vertex AI)"
  type        = string
  default     = "gemini-2.5-flash"
}

variable "public_demo" {
  description = "Grant allUsers run.invoker so judges can open the dashboard. Demo only."
  type        = bool
  default     = false
}
