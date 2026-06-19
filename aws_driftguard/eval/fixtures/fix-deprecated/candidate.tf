resource "aws_s3_bucket" "assets" {
  bucket = "my-assets-bucket"
}

resource "aws_s3_bucket_acl" "assets" {
  bucket = aws_s3_bucket.assets.id
  acl    = "private"
}
