resource "google_storage_bucket" "assets" {
  name                        = "my-assets-bucket"
  location                    = "US"
  uniform_bucket_level_access = true
}
