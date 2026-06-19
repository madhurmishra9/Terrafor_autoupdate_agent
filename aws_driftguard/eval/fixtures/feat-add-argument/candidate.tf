resource "aws_db_instance" "main" {
  identifier          = "app-db"
  engine              = "postgres"
  instance_class      = "db.m6g.large"
  allocated_storage   = 100
  storage_type        = "gp3"
  storage_throughput  = 250
}
