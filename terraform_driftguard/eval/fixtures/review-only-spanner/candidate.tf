resource "google_spanner_database" "db" {
  instance         = "main-instance"
  name             = "app-db"
  database_dialect = "POSTGRESQL"
}
