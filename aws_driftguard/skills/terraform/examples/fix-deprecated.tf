# Example: fix — removing a deprecated argument and migrating to its replacement.
# The `database_flags` inline form is replaced by typed blocks in newer schema.
resource "aws_db_instance" "main" {
  name             = var.instance_name
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = var.tier

    # Replaces the deprecated string-form flag.
    database_flags {
      name  = "max_connections"
      value = "200"
    }
  }
}
