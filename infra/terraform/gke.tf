# GKE Autopilot: the sandbox "victim" app AutoOps watches over. Autopilot
# keeps node management off the plate of a 4-person team on a 5-week clock.
resource "google_container_cluster" "sandbox" {
  name             = "autoops-sandbox"
  location         = var.region
  enable_autopilot = true

  release_channel {
    channel = "REGULAR"
  }

  depends_on = [google_project_service.apis]
}
