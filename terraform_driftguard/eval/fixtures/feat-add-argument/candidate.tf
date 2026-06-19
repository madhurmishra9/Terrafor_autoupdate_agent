resource "google_sql_database_instance" "main" {
  name             = "primary"
  database_version = "POSTGRES_15"
  region           = "us-central1"

  settings {
    tier    = "db-perf-optimized-N-2"
    edition = "ENTERPRISE_PLUS"

    data_cache_config {
      data_cache_enabled = true
    }
  }
}
