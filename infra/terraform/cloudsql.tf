# Cloud SQL (Postgres) backing the sandbox api/worker services. db-f1-micro
# is intentionally small - the db_exhaustion chaos scenario relies on a low
# max_connections ceiling to exhaust quickly and visibly.
resource "google_sql_database_instance" "primary" {
  name             = "cloudsql-primary"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = "db-f1-micro"
    database_flags {
      name  = "max_connections"
      value = "100"
    }
  }

  deletion_protection = false
  depends_on           = [google_project_service.apis]
}

resource "google_sql_database" "app" {
  name     = "autoops"
  instance = google_sql_database_instance.primary.name
}
