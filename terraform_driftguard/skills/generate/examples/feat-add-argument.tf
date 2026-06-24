# Example: feat — adding a new optional argument to an existing resource.
# Provider: hashicorp/google >= 6.0.0
resource "google_sql_database_instance" "main" {
  name             = var.instance_name
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = var.tier

    # New in provider 6.x: data cache for Enterprise Plus edition.
    data_cache_config {
      data_cache_enabled = true
    }
  }
}
