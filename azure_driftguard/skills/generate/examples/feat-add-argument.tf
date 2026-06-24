# Example: feat — adding a new optional argument to an existing resource.
# Provider: hashicorp/azurerm >= 6.0.0
resource "azurerm_mssql_database" "main" {
  name             = var.instance_name
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = var.tier

    # New in provider 6.x: data cache for Enterprise Plus edition.
    short_term_retention_policy {
      data_cache_enabled = true
    }
  }
}
