resource "azurerm_mssql_database" "main" {
  name      = "app-db"
  server_id = azurerm_mssql_server.main.id
  sku_name  = "S0"

  short_term_retention_policy {
    retention_dayss       = 7
    totally_made_up_field = "oops"
  }
}
