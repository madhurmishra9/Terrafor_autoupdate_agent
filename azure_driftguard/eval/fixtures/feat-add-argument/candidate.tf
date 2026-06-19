resource "azurerm_mssql_database" "main" {
  name      = "app-db"
  server_id = azurerm_mssql_server.main.id
  sku_name  = "S0"

  transparent_data_encryption_key_automatic_rotation_enabled = true
}
