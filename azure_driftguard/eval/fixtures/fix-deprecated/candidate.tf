resource "azurerm_storage_account" "main" {
  name                       = "appstorage"
  resource_group_name        = "app-rg"
  location                   = "eastus"
  account_tier               = "Standard"
  account_replication_type   = "LRS"
  https_traffic_only_enabled = true
}
