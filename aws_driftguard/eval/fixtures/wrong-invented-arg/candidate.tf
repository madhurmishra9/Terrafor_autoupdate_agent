resource "aws_db_instance" "main" {
  identifier            = "app-db"
  engine                = "postgres"
  instance_class        = "db.m6g.large"
  allocated_storage     = 100
  log_exports_enabledd  = true
  totally_made_up_field = "oops"
}
