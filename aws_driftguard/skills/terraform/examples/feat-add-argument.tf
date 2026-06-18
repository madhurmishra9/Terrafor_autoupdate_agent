# Example: feat — adding a new optional argument to an existing resource.
# Provider: hashicorp/aws >= 6.0.0
resource "aws_db_instance" "main" {
  name             = var.instance_name
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = var.tier

    # New in provider 6.x: data cache for Enterprise Plus edition.
    storage_throughput {
      data_cache_enabled = true
    }
  }
}
