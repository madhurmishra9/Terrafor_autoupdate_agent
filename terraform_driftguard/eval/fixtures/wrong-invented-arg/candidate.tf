resource "google_sql_database_instance" "main" {
  name             = "primary"
  database_version = "POSTGRES_15"
  region           = "us-central1"

  settings {
    tier = "db-custom-2-7680"

    insights_config {
      query_insights_enabledd = true
      totally_made_up_field   = "oops"
    }
  }
}
