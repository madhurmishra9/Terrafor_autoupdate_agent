resource "azurerm_cosmosdb_account" "main" {
  name                = "app-cosmos"
  resource_group_name = "app-rg"
  location            = "eastus"
  offer_type          = "Standard"

  consistency_policy {
    consistency_level = "BoundedStaleness"
  }
}
